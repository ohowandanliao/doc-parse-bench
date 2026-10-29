# from modules.cal_matrix import cal_text_matrix, cal_table_teds
from registry.registry import EVAL_TASK_REGISTRY
from metrics.show_result import show_result, get_full_labels_results, get_page_split
from registry.registry import METRIC_REGISTRY
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os


def _evaluate_element(args):
    """单个元素类型的评测，用于 ProcessPoolExecutor 并行执行。metric 计算逻辑完全不变。"""
    element, metrics_config, samples_data, save_name, page_info_path = args

    result = {}
    group_info = metrics_config.get('group', [])
    samples = samples_data

    # 同一元素的多个 metric 仍然串行（后一个可能依赖前一个输出），不同元素之间并行
    for metric_name in metrics_config['metric']:
        metric_cls = METRIC_REGISTRY.get(metric_name)
        samples, result_s = metric_cls(samples).evaluate(group_info, f"{save_name}_{element}")
        if result_s:
            result.update(result_s)

    if result:
        print(f'【{element}】')
        show_result(result)

    # 计算 group/page 结果
    md_flag = os.path.isdir(page_info_path)
    if md_flag:
        group_result = {}
        page_result = {}
    else:
        page_info = {}
        with open(page_info_path, 'r') as f:
            pages = json.load(f)
        for page in pages:
            img_path = os.path.basename(page['page_info']['image_path'])
            page_info[img_path[:-4]] = page['page_info']['page_attribute']
        group_result = get_full_labels_results(samples)
        page_result = get_page_split(samples, page_info)

    result_all_element = {
        'all': result,
        'group': group_result,
        'page': page_result
    }

    # 保存元素结果
    if not os.path.exists('./result'):
        os.makedirs('./result')
    if isinstance(samples, list):
        saved_samples = samples
    else:
        saved_samples = samples.samples
    try:
        with open(f'./result/{save_name}_{element}_result.json', 'w', encoding='utf-8') as f:
            json.dump(saved_samples, f, indent=4, ensure_ascii=False)
    except TypeError as e:
        print(f"JSON 序列化错误: {e}")
        print("请检查 saved_samples 中是否包含非 JSON 可序列化的数据类型")

        def find_non_serializable(data):
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        json.dumps(v)
                    except TypeError:
                        print(f"键 '{k}' 包含不可序列化的值: {v} (类型: {type(v)})")
                    find_non_serializable(v)
            elif isinstance(data, (list, tuple)):
                for i, item in enumerate(data):
                    try:
                        json.dumps(item)
                    except TypeError:
                        print(f"索引 {i} 包含不可序列化的项: {item} (类型: {type(item)})")
                    find_non_serializable(item)

        find_non_serializable(saved_samples)

    return element, result_all_element


@EVAL_TASK_REGISTRY.register("end2end_eval")
class End2EndEval():
    @staticmethod
    def _safe_float(val):
        """Convert a metric value to float, treating string 'nan' / 'None' as NaN."""
        import math
        if val is None:
            return math.nan
        if isinstance(val, str):
            val = val.strip().lower()
            if val in ('nan', 'none', 'null', ''):
                return math.nan
            try:
                return float(val)
            except ValueError:
                return math.nan
        try:
            return float(val)
        except (TypeError, ValueError):
            return math.nan

    def _calculate_total_score(self, result_all):
        """
        计算总分: ((1-Text) * 100 + Table + Formula) / 3

        Args:
            result_all: 包含所有评测结果的字典

        Returns:
            float: 计算得到的总分，如果缺少必要数据则返回 None
        """
        import math
        try:
            # 获取 Text 的 Edit_dist (越小越好)
            text_score = None
            if 'text_block' in result_all and result_all['text_block'].get('all'):
                text_all = result_all['text_block']['all']
                if 'Edit_dist' in text_all:
                    text_score = self._safe_float(text_all['Edit_dist'].get('ALL_page_avg'))

            # 获取 Formula 的 Edit_dist (越小越好)
            formula_score = None
            if 'display_formula' in result_all and result_all['display_formula'].get('all'):
                formula_all = result_all['display_formula']['all']
                if 'Edit_dist' in formula_all:
                    formula_score = self._safe_float(formula_all['Edit_dist'].get('ALL_page_avg'))

            # 获取 Table 的 TEDS (越大越好)
            table_score = None
            if 'table' in result_all and result_all['table'].get('all'):
                table_all = result_all['table']['all']
                if 'TEDS' in table_all:
                    table_score = self._safe_float(table_all['TEDS'].get('all'))

            # 检查是否所有必要的分数都存在且为有效数值
            if text_score is None or formula_score is None or table_score is None:
                print(f"Warning: Cannot calculate total score. Missing scores - Text: {text_score}, Table: {table_score}, Formula: {formula_score}")
                return None
            if math.isnan(text_score) or math.isnan(formula_score) or math.isnan(table_score):
                print(f"Warning: Cannot calculate total score. NaN scores - Text: {text_score}, Table: {table_score}, Formula: {formula_score}")
                return None

            # 计算总分: ((1-Text) * 100 + Table + Formula) / 3
            # Text 和 Formula 是 Edit_dist (越小越好，所以用 1-score 转换)
            # Table 是 TEDS (越大越好，范围 0-1，转换为 0-100)
            total = ((1 - text_score) * 100 + table_score * 100 + (1 - formula_score) * 100) / 3

            return total

        except Exception as e:
            print(f"Error calculating total score: {e}")
            return None

    def __init__(self, dataset, metrics_list, page_info_path, save_name):
        result_all = {}

        # 准备并行参数：提取 samples 数据为纯 list，避免 pickle 自定义类
        eval_args = []
        for element in metrics_list.keys():
            samples_obj = dataset.samples[element]
            samples_data = samples_obj.samples if hasattr(samples_obj, 'samples') else samples_obj
            eval_args.append((element, metrics_list[element], samples_data, save_name, page_info_path))

        # 并行执行四个元素类型的评测，进程间完全独立，互不等待
        n_elements = len(metrics_list)
        with ProcessPoolExecutor(max_workers=min(4, n_elements)) as executor:
            futures = {executor.submit(_evaluate_element, args): args[0] for args in eval_args}
            for future in as_completed(futures):
                element, result_all_element = future.result()
                result_all[element] = result_all_element

        # 计算总分
        total_score = self._calculate_total_score(result_all)
        if total_score is not None:
            result_all['total_score'] = total_score
            print('\n' + '='*100)
            print('【Total Score】')
            print(f"Total Score: {total_score:.4f}")
            print('='*100)

        with open(f'./result/{save_name}_metric_result.json', 'w', encoding='utf-8') as f:
            json.dump(result_all, f, indent=4, ensure_ascii=False)
