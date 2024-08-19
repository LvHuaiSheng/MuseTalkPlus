import sys
import shutil
import argparse
from pathlib import Path

import cv2
import torch
import numpy as np
from tqdm import tqdm

sys.path.append('.')

from musetalk_plus.whisper.feature_extractor import AudioFrameExtractor
from musetalk_plus.faces.face_recognize import FaceRecognizer

from common.utils import recreate_multiple_dirs, read_images, video2images, video2audio
from common.setting import (
    TMP_FRAME_DIR, TMP_AUDIO_DIR, TMP_DATASET_DIR,
    VIDEO_FRAME_DIR, AUDIO_FEATURE_DIR, VIDEO_LATENT_DIR
)

device = "cuda" if torch.cuda.is_available() else "cpu"
afe = AudioFrameExtractor(r"F:\models\whisper-tiny-zh")
fr = FaceRecognizer()


def process_video(video_path, fixed_face=True):
    face_location = None
    video_name = video_path.stem
    recreate_multiple_dirs([
        VIDEO_FRAME_DIR / video_name, VIDEO_LATENT_DIR / video_name,
        AUDIO_FEATURE_DIR / video_name, TMP_FRAME_DIR, TMP_AUDIO_DIR
    ])
    # 提取视频帧
    video2images(video_path, TMP_FRAME_DIR)
    # 提取音频
    audio_path = video2audio(video_path, TMP_AUDIO_DIR)
    # 提取特征
    feature_chunks = afe.extract_frames(audio_path)
    img_list = list((TMP_DATASET_DIR / video_name).glob('*'))
    # 截取脸部，如果设置了fixed_face，则只使用第一帧的面部位置截取
    if fixed_face:
        if face_location is None:
            y1, x2, y2, x1 = fr.face_locations(img_list[0])
            face_location = [x1, y1, x2, y2]
        coord_list = [[*face_location] for _ in range(len(img_list))]
    else:
        coord_list = []
        for img in img_list:
            y1, x2, y2, x1 = fr.face_locations(str(img))
            coord_list.append([x1, y1, x2, y2])
    frame_list = read_images(img_list)
    for idx, (coord, frame, chunk) in tqdm(
            enumerate(zip(coord_list, frame_list, feature_chunks)),
            total=len(frame_list),
            desc=f"Processing video: {video_name}"
    ):
        x1, y1, x2, y2 = coord
        crop_frame = frame[y1:y2, x1:x2]
        resized_crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        dst = VIDEO_FRAME_DIR / video_name / f"{idx:08d}.png"
        cv2.imwrite(str(dst), resized_crop_frame)
        dst = AUDIO_FEATURE_DIR / video_name / f"{idx:08d}.npy"
        np.save(str(dst), chunk)
    shutil.rmtree(TMP_DATASET_DIR)


def process_videos(video_dir="./datasets/videos", fixed_face=True):
    video_list = list(Path(video_dir).glob("*.mp4"))
    for video_path in tqdm(video_list, total=len(video_list), desc='Processing videos'):
        process_video(video_path, fixed_face)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--videos_dir",
        type=str,
        default="./datasets/videos"
    )
    parser.add_argument(
        "--fixed_face",
        type=bool,
        default=True
    )
    return parser.parse_args()


def main():
    args = parse_args()
    process_videos(video_dir=args.videos_dir, fixed_face=args.fixed_face)


if __name__ == '__main__':
    main()
