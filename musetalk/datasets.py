import json
import os
import sys
import random
from typing import Literal
from pathlib import Path

import cv2
import torch
import numpy as np
from torch.utils.data import Dataset, DataLoader

sys.path.append('.')
from common.setting import settings
from musetalk.processors import ImageProcessor

RESIZED_IMG = settings.common.image_size
HIDDEN_SIZE = settings.common.hidden_size
EMBEDDING_DIM = settings.common.embedding_dim
device = "cuda" if torch.cuda.is_available() else "cpu"


class MuseTalkDataset(Dataset):
    def __init__(
            self,
            audio_window=2,
            reference_window=5,
            sync_t=5,
            split: Literal['train', 'test', 'all'] = 'all',
    ):
        self.all_data = {}
        self.audio_window = audio_window
        self.reference_window = reference_window
        # 获取多少个连续帧，sync_t最小为1
        assert 1 <= sync_t
        self.sync_t = sync_t
        self.split = split

        self.hidden_dim = (self.audio_window * 2 + 1) * 10
        self.embedding_dim = EMBEDDING_DIM
        self.image_processor = ImageProcessor()
        self.load_filenames()

    @staticmethod
    def sort_files(files):
        return sorted(files, key=lambda x: int(os.path.basename(x).split(".")[0]))

    def load_filenames_from_json(self):
        train_data = {}
        test_data = {}
        if self.split == 'train':
            train_path = Path(settings.dataset.base_dir) / 'train.json'
            with open(train_path, 'r', encoding='utf-8') as f:
                train_data = json.load(f)
                self.all_data = train_data
        if self.split == 'test':
            train_path = Path(settings.dataset.base_dir) / 'train.json'
            with open(train_path, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
                self.all_data = test_data
        if self.split == 'all':
            self.all_data = train_data + test_data
        return self.all_data

    def load_filenames(self):
        if (self.split == 'train' and (Path(settings.dataset.base_dir) / 'train.json').exists()) or \
                (self.split == 'test' and (Path(settings.dataset.base_dir) / 'test.json').exists()):
            return self.load_filenames_from_json()
        else:
            for video_name in os.listdir(settings.dataset.images_dir):
                self.all_data[video_name] = {
                    "image_files": [],
                    "audio_files": [],
                }
                # 各个视频对应的图片路径
                images_dir = os.path.join(settings.dataset.images_dir, video_name)
                for filename in self.sort_files(os.listdir(images_dir)):
                    self.all_data[video_name]["image_files"].append(
                        os.path.join(images_dir, filename)
                    )
                # 各个视频对应的音频路径
                audios_dir = os.path.join(settings.dataset.audios_dir, video_name)
                for filename in self.sort_files(os.listdir(audios_dir)):
                    self.all_data[video_name]["audio_files"].append(
                        os.path.join(audios_dir, filename)
                    )
                # 保证图片和音频是帧数一样
                max_length = min(
                    len(self.all_data[video_name]['image_files']),
                    len(self.all_data[video_name]['audio_files']),
                )
                self.all_data[video_name]['image_files'] = self.all_data[video_name]['image_files'][:max_length]
                self.all_data[video_name]['audio_files'] = self.all_data[video_name]['audio_files'][:max_length]
                # 过滤5秒以下的视频
                if len(self.all_data[video_name]['image_files']) < 25 * 5:
                    del self.all_data[video_name]
            return self.all_data

    def load_audio_feature_with_window(self, video_name, frame_idx: int):
        # 单帧audio_feature形状为5*2*384
        audio_window_feature = np.zeros((self.hidden_dim, self.embedding_dim))
        min_idx = max(0, frame_idx - self.audio_window)
        max_idx = min(frame_idx + self.audio_window, len(self.all_data[video_name]['audio_files']) - 1)
        for idx, fidx in enumerate(range(min_idx, max_idx)):
            file = self.all_data[video_name]['audio_files'][fidx]
            audio_feature = np.load(file)
            audio_window_feature[idx * 10: (idx + 1) * 10, :] = audio_feature
        return torch.FloatTensor(audio_window_feature)

    def load_frames(self, video_name, frame_idx: int):
        # reference_frame范围为[0, frame_idx-self.reference_window] & [frame_idx+self.reference_window, len]
        reference_frame_idx = random.randint(0, len(self.all_data[video_name]['image_files']) - 1)
        while abs(reference_frame_idx - frame_idx) <= self.reference_window:
            reference_frame_idx = random.randint(0, len(self.all_data[video_name]['image_files']) - 1)
        frame_list = [frame_idx, reference_frame_idx]
        images = []
        for frame_idx in frame_list:
            images.append(self.load_frame(video_name, frame_idx))
        images.append(self.load_frame(video_name, frame_idx, True))
        # images三个元素分别为, target_image, reference, masked_image
        return images

    def load_frame(self, video_name, frame_idx, half_masked=False):
        image = cv2.imread(self.all_data[video_name]['image_files'][frame_idx])
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return self.image_processor(image, half_mask=half_masked)

    @staticmethod
    def filename2num(filepath):
        return int(os.path.basename(filepath).split(".")[0])

    def __len__(self):
        return sum([len(self.all_data[video_name]['image_files']) for video_name in self.all_data.keys()])

    def __getitem__(self, idx):
        # 随机选一个视频
        video_name = random.choice(list(self.all_data.keys()))
        video_data = self.all_data[video_name]
        # 选取self.sync_t帧图像
        frame_idx = random.randint(0, len(video_data['image_files']) - 1 - self.sync_t)
        frame_idxes = [frame_idx + i for i in range(self.sync_t)]
        target_images = torch.zeros(self.sync_t, 3, RESIZED_IMG, RESIZED_IMG)
        reference_images = torch.zeros(self.sync_t, 3, RESIZED_IMG, RESIZED_IMG)
        masked_images = torch.zeros(self.sync_t, 3, RESIZED_IMG, RESIZED_IMG)
        audio_features = torch.zeros(self.sync_t, self.hidden_dim, self.embedding_dim)
        for idx, frame_idx in enumerate(frame_idxes):
            target_image, reference_image, masked_image = self.load_frames(video_name, frame_idx)
            # 获取对应音频即window中的音频
            audio_feature = self.load_audio_feature_with_window(video_name, frame_idx)
            target_images[idx] = target_image
            reference_images[idx] = reference_image
            masked_images[idx] = masked_image
            audio_features[idx] = audio_feature
        return target_images, reference_images, masked_images, audio_features


class SyncNetDataset(MuseTalkDataset):
    def __getitem__(self, item):
        # 随机选一个视频
        video_name = random.choice(list(self.all_data.keys()))
        video_data = self.all_data[video_name]
        # 选取self.sync_t帧图像
        frame_idx = random.randint(0, len(video_data['image_files']) - 1 - self.sync_t)
        frame_idxes = [frame_idx + i for i in range(self.sync_t)]
        images = torch.zeros(self.sync_t, 3, RESIZED_IMG, RESIZED_IMG)
        # 随机生成标签
        label = torch.randint(0, 2, (1,))
        for idx, frame_idx in enumerate(frame_idxes):
            target_image, *_ = self.load_frames(video_name, frame_idx)
            images[idx] = target_image

        # 加载音频数据
        if label.item() == 0:
            # 标签为False，选择与视频不匹配的audio
            mismatch_frame_idx = random.randint(0, len(video_data['image_files']) - 1 - self.sync_t)
            while abs(mismatch_frame_idx - frame_idx) <= self.sync_t:
                mismatch_frame_idx = random.randint(0, len(video_data['image_files']) - 1 - self.sync_t)
            frame_idx = frame_idx
        frame_idxes = [frame_idx + i for i in range(self.sync_t)]
        audio_features = torch.zeros(self.sync_t, self.hidden_dim, self.embedding_dim)
        for idx, frame_idx in enumerate(frame_idxes):
            audio_feature = self.load_audio_feature_with_window(video_name, frame_idx)
            audio_features[idx] = audio_feature
        t, c, h, w = images.shape
        return images.view((t * c, h, w)), audio_features, label


if __name__ == '__main__':
    # ds = MuseTalkDataset()
    # ld = DataLoader(ds, batch_size=4, shuffle=True)
    # for i in ld:
    #     t, r, m, a = i
    #     print(t.shape)
    #     print(r.shape)
    #     print(m.shape)
    #     print(a.shape)
    #     break
    ds = SyncNetDataset()
    ld = DataLoader(ds, batch_size=4, shuffle=True)
    for i in ld:
        t, a, l = i
        print(t.shape)
        print(a.shape)
        print(l.shape)
        break
