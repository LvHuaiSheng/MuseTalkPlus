import sys
import shutil
import argparse
from pathlib import Path
from typing import Union

import cv2
import torch
import numpy as np
from tqdm import tqdm

sys.path.append('.')

from musetalk_plus.faces.face_analysis import FaceAnalyst
from musetalk_plus.audio.feature_extractor import AudioFrameExtractor
from musetalk_plus.audio.audio_feature_extract import AudioFeatureExtractor

from common.setting import settings
from common.utils import read_images, video2images, video2audio, make_multiple_dirs
from common.setting import (
    TMP_FRAME_DIR, TMP_AUDIO_DIR, TMP_DATASET_DIR,
    VIDEO_FRAME_DIR, AUDIO_FEATURE_DIR,
)

device = "cuda" if torch.cuda.is_available() else "cpu"
afe: Union[AudioFeatureExtractor, AudioFrameExtractor]
fa = FaceAnalyst(settings.models.dwpose_config_path, settings.models.dwpose_model_path)


def process_video(video_path):
    video_name = video_path.stem
    make_multiple_dirs([TMP_FRAME_DIR, TMP_AUDIO_DIR])
    # 视频部分的预处理
    if not (VIDEO_FRAME_DIR / video_name).exists():
        VIDEO_FRAME_DIR.mkdir(exist_ok=True)
        (VIDEO_FRAME_DIR / video_name).mkdir(exist_ok=True)
        video2images(video_path, TMP_FRAME_DIR)
        frame_list = read_images([str(img) for img in TMP_FRAME_DIR.glob('*')])
    else:
        frame_list = []
    for fidx, frame in tqdm(
            enumerate(frame_list),
            total=len(frame_list),
            desc=f"Processing video: {video_name}"
    ):
        pts = fa.analysis(frame)
        bbox = fa.face_location(pts)
        x1, y1, x2, y2 = bbox
        crop_frame = frame[y1:y2, x1:x2]
        resized_crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        dst = VIDEO_FRAME_DIR / video_name / f"{fidx:08d}.png"
        cv2.imwrite(str(dst), resized_crop_frame)
    # 音频部分的预处理
    if not (AUDIO_FEATURE_DIR / video_name).exists():
        AUDIO_FEATURE_DIR.mkdir(exist_ok=True)
        (AUDIO_FEATURE_DIR / video_name).mkdir(exist_ok=True)
        audio_path = video2audio(video_path, TMP_AUDIO_DIR)
        feature_chunks = afe.extract_features(audio_path)
    else:
        feature_chunks = []
    for fidx, chunk in tqdm(
            enumerate(feature_chunks),
            total=len(feature_chunks),
            desc=f"Processing video {video_name} 's audio"
    ):
        dst = AUDIO_FEATURE_DIR / video_name / f"{fidx:08d}.npy"
        np.save(str(dst), chunk)
    shutil.rmtree(TMP_DATASET_DIR)


def process_videos(video_dir="./datasets/videos"):
    video_list = list(Path(video_dir).glob("*.mp4"))
    for video_path in tqdm(video_list, total=len(video_list), desc='Processing videos'):
        process_video(video_path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--videos_dir",
        type=str,
        default="./datasets/videos"
    )
    parser.add_argument(
        "--reliable",
        type=bool,
        default=True
    )
    return parser.parse_args()


def main():
    args = parse_args()
    global afe
    if args.reliable:
        afe = AudioFeatureExtractor(settings.models.whisper_path, device=device, dtype=torch.float32)
    else:
        afe = AudioFrameExtractor(settings.models.whisper_fine_tuning_path)
    process_videos(video_dir=args.videos_dir)


if __name__ == '__main__':
    main()
