import os
import shutil
import time
import subprocess
from functools import partial
from concurrent.futures import ThreadPoolExecutor

import cv2
from tqdm import tqdm


def timeit(func):
    def inner(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} speed: {(end - start) * 1000:.2f} ms")
        return result

    return inner


def video2images(vid_path, save_path):
    output_pattern = os.path.join(save_path, "%08d.png")
    ffmpeg_command = [
        "ffmpeg",
        "-i", vid_path,
        "-vf", "fps=25",
        output_pattern
    ]
    try:
        subprocess.run(ffmpeg_command, check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        print(f"Frames extracted to {save_path}")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")


def make_multiple_dirs(path_list):
    for path in path_list:
        os.makedirs(path) if not os.path.exists(path) else None


def remove_multiple_dirs(path_list):
    for path in path_list:
        # os.removedirs(path) if os.path.exists(path) else None
        shutil.rmtree(path) if os.path.exists(path) else None


def recreate_multiple_dirs(path_list):
    remove_multiple_dirs(path_list)
    make_multiple_dirs(path_list)


def read_images(img_list, grayscale=False):
    frames = []
    with ThreadPoolExecutor() as executor:
        # Use partial to fix the flags parameter for cv2.imread
        if grayscale:
            imread = partial(cv2.imread, cv2.IMREAD_GRAYSCALE)
        else:
            imread = cv2.imread
        for frame in tqdm(executor.map(imread, img_list), total=len(img_list), desc='Reading images'):
            frames.append(frame)
    return frames
