import json
import os
from collections import defaultdict
from utils.extract import md_tex_filter
from utils.match import match_gt2pred_simple, match_gt2pred_no_split
from utils.match_quick import match_gt2pred_quick
# from utils.match_full import match_gt2pred_full, match_gt2pred_textblock_full
from utils.read_files import read_md_file
from registry.registry import DATASET_REGISTRY
from dataset.recog_dataset import *
import pdb
import Levenshtein
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed


def _get_order_paired(order_match_s, img_name):
    """计算 GT 和 Pred 阅读顺序之间的编辑距离（独立函数，供子进程调用）。"""
    matched = [(item['gt_position'], item['pred_position']) for item in order_match_s if (item['gt_position'] != [""] and item['pred_position'] != "")]
    gt_idx_all = [item['gt_position'] for item in order_match_s if (item['gt_position'] != [""])]
    read_order_pred = [i[0] for i in sorted(matched, key=lambda x: x[1])]
    read_order_gt = sum(gt_idx_all, [])
    read_order_gt = [x for x in read_order_gt if x]
    gt = sorted(read_order_gt)
    pred = sum(read_order_pred, [])
    pred = [x for x in pred if x]
    if len(pred) > 0 or len(gt) > 0:
        edit = Levenshtein.distance(gt, pred) / max(len(pred), len(gt))
        return {'gt': gt, 'pred': pred, 'img_id': img_name, 'edit': edit}
    else:
        return {}


def _match_single_doc(args):
    """单篇文档的 GT-Pred 匹配，用于 ProcessPoolExecutor 并行执行。"""
    doc_idx, sample_name, gt_folder, pred_folder, match_method, total_docs = args

    if not sample_name.endswith('.md'):
        return None

    img_name = sample_name[:-3] + '.jpg'
    gt_content = read_md_file(os.path.join(gt_folder, sample_name))
    pred_path = os.path.join(pred_folder, sample_name)
    if not os.path.exists(pred_path):
        print(f'!!!WARNING: No prediction for {sample_name}')
        return None
    pred_content = read_md_file(pred_path)

    if match_method == 'simple_match':
        match_fn = match_gt2pred_simple
    elif match_method == 'quick_match':
        match_fn = match_gt2pred_quick
    elif match_method == 'no_split':
        match_fn = match_gt2pred_no_split
    else:
        match_fn = match_gt2pred_quick

    gt_dataset = md_tex_filter(gt_content)
    pred_dataset = md_tex_filter(pred_content)

    plain_text_match_clean = []
    display_formula_match_s = []
    latex_table_match_s = []
    html_table_match_s = []
    order_match_single = None

    if gt_dataset['text_all']:
        plain_text_match_s = match_fn(gt_dataset['text_all'], pred_dataset['text_all'], 'text', img_name)
        plain_text_match_clean = plain_text_match_s

    if gt_dataset.get('equation_isolated'):
        display_formula_match_s = match_fn(
            gt_dataset['equation_isolated'], pred_dataset['equation_isolated'], 'formula', img_name
        )
        display_formula_match_s = [
            x for x in display_formula_match_s
            if x['gt_idx'] != [""] and x['gt_category_type'] != 'equation_inline'
        ]

    if gt_dataset.get('latex_table') and pred_dataset.get('latex_table'):
        table_match_s = match_fn(gt_dataset['latex_table'], pred_dataset['latex_table'], 'latex_table', img_name)
        latex_table_match_s = [x for x in table_match_s if x['gt_idx'] != [""]]
    elif gt_dataset.get('html_table') and pred_dataset.get('html_table'):
        table_match_s = match_fn(gt_dataset['html_table'], pred_dataset['html_table'], 'html_table', img_name)
        html_table_match_s = [x for x in table_match_s if x['gt_idx'] != [""]]
    else:
        if gt_dataset.get('latex_table') or gt_dataset.get('html_table'):
            print('GT table is not empty. But pred is empty or its format is different from gt.')
        if pred_dataset.get('latex_table') or pred_dataset.get('html_table'):
            print('Pred table is not empty. But gt is empty or its format is different from pred.')

    order_match_s = _get_order_paired(plain_text_match_clean, img_name)
    if order_match_s:
        order_match_single = order_match_s

    return {
        'plain_text': plain_text_match_clean,
        'display_formula': display_formula_match_s,
        'latex_table': latex_table_match_s,
        'html_table': html_table_match_s,
        'order': order_match_single,
    }


@DATASET_REGISTRY.register("md2md_dataset")
class Md2MdDataset():
    def __init__(self, cfg_task):
        gt_folder = cfg_task['dataset']['ground_truth']['data_path']
        pred_folder = cfg_task['dataset']['prediction']['data_path']
        self.match_method = cfg_task['dataset'].get('match_method', 'simple_match')

        self.samples = self.get_matched_elements(gt_folder, pred_folder)

    def __getitem__(self, cat_name, idx):
        return self.samples[cat_name][idx]

    def get_order_paired(self, order_match_s, img_name):
        """保留原方法签名，委托给独立函数。"""
        return _get_order_paired(order_match_s, img_name)

    def get_matched_elements(self, gt_folder, pred_folder):
        doc_names = sorted([s for s in os.listdir(gt_folder) if s.endswith('.md')])
        total = len(doc_names)

        if total == 0:
            return {
                'text_block': DATASET_REGISTRY.get('recogition_end2end_base_dataset')([]),
                'display_formula': DATASET_REGISTRY.get('recogition_end2end_base_dataset')([]),
                'table': DATASET_REGISTRY.get('recogition_end2end_table_dataset')([], 'html'),
                'reading_order': DATASET_REGISTRY.get('recogition_end2end_base_dataset')([]),
            }

        match_args = [
            (i + 1, name, gt_folder, pred_folder, self.match_method, total)
            for i, name in enumerate(doc_names)
        ]

        plain_text_match = []
        display_formula_match = []
        html_table_match = []
        latex_table_match = []
        order_match = []

        workers = min(os.cpu_count() or 1, total)
        idx_to_name = {i + 1: name for i, name in enumerate(doc_names)}
        done_set: set[int] = set()
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_match_single_doc, args): args[0] for args in match_args}
            with tqdm(total=total, desc=f"Matching [0/{total}]", unit="doc") as pbar:
                for future in as_completed(futures):
                    doc_idx = futures[future]
                    result = future.result()
                    if result is not None:
                        plain_text_match.extend(result['plain_text'])
                        display_formula_match.extend(result['display_formula'])
                        latex_table_match.extend(result['latex_table'])
                        html_table_match.extend(result['html_table'])
                        if result['order'] is not None:
                            order_match.append(result['order'])
                    done = pbar.n + 1
                    done_set.add(doc_idx)
                    pbar.set_description_str(f"Matching [{done}/{total}]")
                    pbar.update(1)
                    if total - done <= 15:
                        remaining = [idx_to_name[i] for i in range(1, total + 1)
                                     if i not in done_set]
                        tqdm.write(f"  剩余 {len(remaining)} 篇: {remaining}")

        if latex_table_match:
            table_match = latex_table_match
            table_format = 'latex'
        else:
            table_match = html_table_match
            table_format = 'html'

        matched_samples_all = {
            'text_block': DATASET_REGISTRY.get('recogition_end2end_base_dataset')(plain_text_match),
            'display_formula': DATASET_REGISTRY.get('recogition_end2end_base_dataset')(display_formula_match),
            'table': DATASET_REGISTRY.get('recogition_end2end_table_dataset')(table_match, table_format),
            'reading_order': DATASET_REGISTRY.get('recogition_end2end_base_dataset')(order_match)
        }

        return matched_samples_all
