from typing import Tuple
from operator import itemgetter

import cv2
import numpy as np
from skimage.metrics import structural_similarity


ALPHA_THRESHOLD = 200


# 使用边缘检测模糊确定缺口位置
def _check_gap_position_roughly(reordered_fullbg_img: np.ndarray, reordered_bg_img: np.ndarray) \
        -> Tuple[int, int, int, int]:
    height, width = reordered_bg_img.shape[:2]
    _, img = structural_similarity(reordered_fullbg_img, reordered_bg_img, multichannel=True, full=True)

    gray_img = cv2.cvtColor((img * 255).astype("uint8"), cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray_img, (5, 5), 0)

    # 相同为 0，不同为 1
    thresh_scores = 1 - cv2.threshold(blur, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    scores = np.sum(thresh_scores, axis=0)
    left = -1
    for i in range(width):
        max_score = max(scores[i: i + 4])
        min_score = min(scores[i: i + 4])
        if min_score >= 7 >= max_score - min_score:
            print(f'left     {scores[i: i + 4]} {i}')
            left = i
            break

    right = -1
    for i in range(width - 1, -1, -1):
        max_score = max(scores[i - 3: i + 1])
        min_score = min(scores[i - 3: i + 1])
        if min_score >= 7 >= max_score - min_score:
            print(f'right    {scores[i - 3: i + 1]} {i}')
            right = i
            break

    scores = np.sum(thresh_scores, axis=1)
    up = -1
    for i in range(height):
        max_score = max(scores[i: i + 4])
        min_score = min(scores[i: i + 4])
        if min_score >= 7 >= max_score - min_score:
            print(f'up       {scores[i: i + 4]} {i}')
            up = i
            break

    down = -1
    for i in range(height - 1, -1, -1):
        max_score = max(scores[i - 3: i + 1])
        min_score = min(scores[i - 3: i + 1])
        if min_score >= 7 >= max_score - min_score:
            print(f'down     {scores[i - 3: i + 1]} {i}')
            down = i
            break

    # cv2.imshow("thresh", thresh_scores*255)
    return left, up, right, down


# 根据图片 ALPHA 通道切割豁口图片
def _crop_gap_img(gap_img: np.ndarray):
    alpha_channel = gap_img[:, :, 3]
    filter_alpha = alpha_channel <= ALPHA_THRESHOLD
    gap_height, gap_width = gap_img.shape[:2]

    left = right = up = down = -1

    for left in range(gap_width):
        if not np.all(filter_alpha[:, left]):
            break

    for right in range(gap_width - 1, -1, -1):
        if not np.all(filter_alpha[:, right]):
            break

    for up in range(gap_height):
        if not np.all(filter_alpha[up, :]):
            break

    for down in range(gap_height - 1, -1, -1):
        if not np.all(filter_alpha[down, :]):
            break

    cropped_gap_img = gap_img[up: down + 1, left:right + 1]
    return left, up, cropped_gap_img


def _search(
        gap_img: np.ndarray, reordered_fullbg_img: np.ndarray, filter_alpha: np.ndarray,
        left: int, up: int, right: int, down: int, cache: dict) -> Tuple[int, int]:
    gap_height, gap_width = gap_img.shape[:2]
    result = []
    rgb_gap_img = cv2.cvtColor(gap_img, cv2.COLOR_RGBA2RGB)

    for x in range(left, right - gap_width):
        for y in range(up, down - gap_height):
            if (x, y) in cache:
                score = cache[(x, y)]
            else:

                matched_img = np.where(filter_alpha,
                                       rgb_gap_img,
                                       reordered_fullbg_img[y: y + gap_height, x: x + gap_width]
                                       )
                score = structural_similarity(matched_img, rgb_gap_img, multichannel=True)
                cache[(x, y)] = score
            if score >= 0.5:
                result.append((x, y, score))

    if result:
        result.sort(key=itemgetter(2), reverse=True)
        print('匹配图片结果', len(result), result[:20])
        x, y = result[0][:2]
        return x, y
    return -1, -1


def check_gap_position(
        reordered_fullbg_img: np.ndarray, reordered_bg_img: np.ndarray, gap_img: np.ndarray,
        verbose=False) -> int:
    assert reordered_bg_img.shape == reordered_fullbg_img.shape
    height, width = reordered_bg_img.shape[:2]

    left, up, right, down = _check_gap_position_roughly(
        reordered_fullbg_img=reordered_fullbg_img,
        reordered_bg_img=reordered_bg_img)
    cv2.rectangle(reordered_bg_img, (left, up), (right, down), (0, 255, 0), 1)

    cropped_gap_img_left, cropped_gap_img_up, cropped_gap_img = _crop_gap_img(gap_img)
    # cv2.imshow('cropped_gap_img', cropped_gap_img)
    # cv2.waitKey()

    # 整个搜索过程以中心处开始，一圈一圈扩散式搜索；实际代码还是按行按列的，加一个 cache 防止重复扫描
    cache = {}
    filter_alpha = (cropped_gap_img[:, :, 3] <= ALPHA_THRESHOLD)[:, :, np.newaxis]
    for step in (3, 5, 9, 14, 20):
        area_left = max(0, left - step)
        area_up = max(0, up - step)
        area_right = min(width - 1, right + step)
        area_down = min(height - 1, down + step)

        cv2.rectangle(reordered_bg_img, (area_left, area_up), (area_right, area_down), (255, 0, 0), 1)
        # cv2.imshow("reordered_bg_img1", reordered_bg_img)
        # cv2.waitKey()

        x, y = _search(cropped_gap_img, reordered_fullbg_img, filter_alpha,
                       left=area_left, up=area_up, right=area_right, down=area_down, cache=cache)
        if x >= 0 and y >= 0:
            break

    # 偏移抵消（cropped_gap_img 是原 gap_img 的截了一部分）
    x, y = x - cropped_gap_img_left, y - cropped_gap_img_up
    if verbose:
        gap_height, gap_width = gap_img.shape[:2]
        for i in range(gap_height):
            for j in range(gap_width):
                if gap_img[i, j][3] >= ALPHA_THRESHOLD:
                    reordered_bg_img[y + i, x + j] = gap_img[i, j][:3]

        cv2.line(reordered_bg_img, (x, 0), (x, height), (0, 0, 255), 1)
        cv2.line(reordered_bg_img, (x + gap_width, 0), (x + gap_width, height), (0, 0, 255), 1)
        cv2.line(reordered_bg_img, (0, y), (width, y), (0, 0, 255), 1)
        cv2.line(reordered_bg_img, (0, y + gap_height), (width, y + gap_height), (0, 0, 255), 1)
        cv2.imshow("result", reordered_bg_img)
        cv2.waitKey()

    return x
