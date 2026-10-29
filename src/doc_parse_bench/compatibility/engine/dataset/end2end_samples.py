import os
from registry.registry import DATASET_REGISTRY
from .recog_dataset import RecognitionTableDataset
from utils.data_preprocess import normalized_table, clean_string
@DATASET_REGISTRY.register("recogition_end2end_base_dataset")
class RecognitionEnd2EndBaseDataset():
    def __init__(self, samples):
        img_id = 0
        for sample in samples:
            if not sample.get('img_id'):
                sample['img_id'] = img_id
            img_id += 1
        self.samples = samples
    def __getitem__(self, idx):
        return self.samples[idx]

@DATASET_REGISTRY.register("recogition_end2end_table_dataset")
class RecognitionEnd2EndTableDataset(RecognitionTableDataset):
    def __init__(self, samples, table_format):
        self.pred_table_format = table_format
        self.samples = self.normalize_data(samples)

    def normalize_data(self, samples):
        img_id = 0

        for sample in samples:
            p = sample['pred']
            r = sample['gt']
            p = normalized_table(p, self.pred_table_format)
            r = normalized_table(r)
            sample['norm_gt'] = r
            sample['norm_pred'] = p
            sample['img_id'] = sample['img_id'] if sample.get('img_id') else img_id
            img_id += 1

        return samples
