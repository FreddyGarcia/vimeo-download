#!/usr/bin/env python

import requests
import base64
from tqdm import tqdm
from moviepy.editor import VideoFileClip, concatenate_videoclips
from urllib import parse as urlparse
import subprocess as sp
import os
import distutils.core
import argparse
import datetime

import random
import string
import re
import shutil

# Prefix for this run
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
SALT = ''.join(random.choice(string.digits) for _ in range(3))
OUT_PREFIX = TIMESTAMP + '-' + SALT

# Create temp and output paths based on where the executable is located
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# create temp directory right before we need it
INSTANCE_TEMP = os.path.join(TEMP_DIR, OUT_PREFIX)

try:
    FFMPEG_BIN = distutils.spawn.find_executable("ffmpeg")
except AttributeError:
    FFMPEG_BIN = 'ffmpeg'

def initialize():
    for directory in (TEMP_DIR, OUTPUT_DIR):
        if not os.path.exists(directory):
            print("Creating {}...".format(directory))
            os.makedirs(directory)

def clean():
    for directory in (TEMP_DIR, OUTPUT_DIR):
        if os.path.exists(directory):
            print("Creating {}...".format(directory))
            shutil.rmtree(directory)

def download_video(base_url, content):
    """Downloads the video portion of the content into the INSTANCE_TEMP folder"""
    result = True
    heights = [(i, d['height']) for (i, d) in enumerate(content)]
    idx, _ = max(heights, key=lambda t: t[1])
    video = content[idx]
    video_base_url = urlparse.urljoin(base_url, video['base_url'])
    print('video base url:', video_base_url)

    # Create INSTANCE_TEMP if it doesn't exist
    if not os.path.exists(INSTANCE_TEMP):
        print("Creating {}...".format(INSTANCE_TEMP))
        os.makedirs(INSTANCE_TEMP)

    # Download the video portion of the stream
    filename = os.path.join(INSTANCE_TEMP, "v.mp4")
    print('saving to %s' % filename)

    video_file = open(filename, 'wb')

    init_segment = base64.b64decode(video['init_segment'])
    video_file.write(init_segment)

    for segment in tqdm(video['segments']):
        segment_url = video_base_url + segment['url']
        resp = requests.get(segment_url, stream=True)
        if resp.status_code != 200:
            print('not 200!')
            print(resp)
            print(segment_url)
            result = False
            break
        for chunk in resp:
            video_file.write(chunk)

    video_file.flush()
    video_file.close()
    return result

def download_audio(base_url, content):
    """Downloads the video portion of the content into the INSTANCE_TEMP folder"""
    result = True
    audio = content[0]
    audio_base_url = urlparse.urljoin(base_url, audio['base_url'])
    print('audio base url:', audio_base_url)

    # Create INSTANCE_TEMP if it doesn't exist
    if not os.path.exists(INSTANCE_TEMP):
        print("Creating {}...".format(INSTANCE_TEMP))
        os.makedirs(INSTANCE_TEMP)

    # Download
    filename = os.path.join(INSTANCE_TEMP, "a.mp3")
    print('saving to %s' % filename)

    audio_file = open(filename, 'wb')

    init_segment = base64.b64decode(audio['init_segment'])
    audio_file.write(init_segment)

    for segment in tqdm(audio['segments']):
        segment_url = audio_base_url + segment['url']
        resp = requests.get(segment_url, stream=True)
        if resp.status_code != 200:
            print('not 200!')
            print(resp)
            print(segment_url)
            result = False
            break
        for chunk in resp:
            audio_file.write(chunk)

    audio_file.flush()
    audio_file.close()
    return result

def merge_audio_video(output_filename):
    audio_filename = os.path.join(TEMP_DIR, OUT_PREFIX, "a.mp3")
    video_filename = os.path.join(TEMP_DIR, OUT_PREFIX, "v.mp4")
    command = [ FFMPEG_BIN,
            '-i', audio_filename,
            '-i', video_filename,
            '-acodec', 'copy',
            '-vcodec', 'copy',
            output_filename ]
    print("ffmpeg command is:", command)

    sp.call(command)

def read_file(file_path):
    for line in open(file_path):
        _line = line.replace('\n', '')
        yield _line

def save_bad_download(url):
    with open("errors.txt", "a+") as f:
        f.write(url)

def get_master_json_url(url):
    res = requests.get(url)
    reg = r"(http|https)://([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?"
    occurs = re.finditer(reg, res.text)
    first = [c.group() for c in occurs if 'master.json' in c.group()][0]
    return first

def concat_videos(output_filename):
    ls = os.listdir(OUTPUT_DIR)
    ls_sorted = sorted(ls, key=lambda x: int(x.split('_')[0]))

    ls_concat = []
    for v_path in ls_sorted:
        ls_concat.append(VideoFileClip(os.path.join(OUTPUT_DIR, v_path)))

    final_video = concatenate_videoclips(ls_concat)
    final_video.write_videofile(output_filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", action="store", help="file path contaninig vimeo urls")
    parser.add_argument("-s", "--skip", action="store", help="skip n number of lines")
    parser.add_argument("-o", "--output", action="store", help="Concat videos")
    args = parser.parse_args()

    if args.output:
        concat_videos(args.output)
        quit()

    # quit if not file recieved
    if not args.file: quit()

    # check path valid
    if not os.path.isfile(args.file):
        print(args.file + " not a valid file")
        quit()


    # get a generator from file
    urls = read_file(args.file)
    file_basename = os.path.basename(args.file.split('.')[-2])

    for i, url in enumerate(urls):

        if args.skip:
            skip = int(args.skip)
            if i < skip:
                continue

        output_filename = os.path.join(OUTPUT_DIR, f'{i}_' + file_basename + '.mp4')
        print("Output filename set to:", output_filename)

        try:
            master_json_url = get_master_json_url(url)
        except Exception as ex:
            # save error url on excepcion
            save_bad_download(url)
            quit()

        resp = requests.get(master_json_url)
        if resp.status_code != 200:
            match = re.search('<TITLE>(.+)<\/TITLE>', resp.content, re.IGNORECASE)
            title = match.group(1)
            print('HTTP error (' + str(resp.status_code) + '): ' + title)
            quit(0)

        content = resp.json()
        base_url = urlparse.urljoin(master_json_url, content['base_url'])

        if not download_video(base_url, content['video']) or not download_audio(base_url, content['audio']):
            save_bad_download(url)
            quit()

        merge_audio_video(output_filename)

    # concat all files
    concat_videos(file_basename + '.mp4')
