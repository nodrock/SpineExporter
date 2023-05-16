import math
import multiprocessing
import shutil
import subprocess
import os
import json
import sys
import argparse
import concurrent.futures
import tempfile
import time
from PIL import Image


def modify_export_json(export_json_path, spine_file, output, export_scale):
    # Read in the export.json file
    with open(export_json_path, "r") as f:
        export_data = json.load(f)

    # Modify the "project" and "packAtlas.scale" properties
    export_data["project"] = spine_file
    export_data["output"] = output
    export_data["packAtlas"]["scale"] = [export_scale]
    # [f"{export_scale:.2f}"]

    # Write the modified export.json file
    with open(export_json_path, "w") as f:
        json.dump(export_data, f, indent=4)


def check_output_folder(output):
    # Check if there is only one .png file in the output folder
    png_files = [f for f in os.listdir(output) if f.endswith(".png")]
    if len(png_files) == 1:
        return True
    else:
        return False


def try_export(export_json_path, export_scale, output_path, spine_file, spine_params):
    modify_export_json(export_json_path, spine_file, output_path, export_scale)
    # print(f"Trying with scale {export_scale}...", end="\r")
    # sys.stdout.flush()
    result = subprocess.run(spine_params, capture_output=True)
    if result.returncode != 0:
        output = result.stdout.decode()
        if "Image does not fit within max page" not in output:
            print(f"Error while exporting {spine_file} with scale {export_scale}:\n {result.stdout.decode()}")
        return False
    return check_output_folder(output_path)


def export_spine(spine_exec, export_json, spine_file, output, base_path=None):
    tmp_dir = tempfile.mkdtemp()
    start_time = time.time()
    print(f"Processing {os.path.basename(spine_file)}... ({tmp_dir})")
    export_scale = 1.0
    output_path = output if output is not None \
        else f"{os.path.splitext(spine_file)[0]}_export"
    # Create the output directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    export_json_path = os.path.join(tmp_dir, "export.json")
    shutil.copyfile(export_json, export_json_path)
    spine_params = [spine_exec,
                    "--input", spine_file,
                    "--output", output_path,
                    "--export", os.path.join(tmp_dir, export_json_path)]

    failed = False
    # Try to find proper scale
    if not try_export(export_json_path, export_scale, output_path, spine_file, spine_params):
        left = 10
        right = 100
        ok_value = 100
        while left <= right:
            middle = (left + right) // 2
            if middle % 2 == 1:
                middle += 1
            if try_export(export_json_path, middle / 100, output_path, spine_file, spine_params):
                ok_value = middle
                # print(f"{left:3} {right:3}  middle = {middle:3}  is_too_much = False   last_ok_value = {ok_value}")
                left = middle + 2
            else:
                # print(f"{left:3} {right:3}  middle = {middle:3}  is_too_much = True    last_ok_value = {ok_value}")
                right = middle - 2

        # Do a final export with the last ok value
        if ok_value != 100:
            export_scale = ok_value / 100
            try_export(export_json_path, export_scale, output_path, spine_file, spine_params)
        else:
            failed = True

        # while not check_output_folder(output_path):
        #     export_scale -= 0.1
        #     try_export(export_scale, output_path, spine_file, spine_params)
        #
        # while check_output_folder(output_path):
        #     export_scale += 0.02
        #     try_export(export_scale, output_path, spine_file, spine_params)
        #
        # export_scale -= 0.02
        # try_export(export_scale, output_path, spine_file, spine_params)

    end_time = time.time()
    elapsed_time = end_time - start_time
    if base_path is not None:
        spine_file = os.path.relpath(spine_file, base_path)
    if failed:
        print(f"Failed for '{spine_file}' output='{output_path}' in {elapsed_time:.2f}s")
    else:
        png_files = [f for f in os.listdir(output_path) if f.endswith(".png")]
        png_file = os.path.join(output_path, png_files[0])
        width, height = get_png_resolution(png_file)

        print(f"Export completed for '{spine_file}' scale={export_scale} ({width}x{height}) output='{output_path}' in {elapsed_time:.2f}s")
    shutil.rmtree(tmp_dir)


def run_export_in_threads(spine_paths, output, spine_exec, export_json, base_path, max_workers):
    print(f"Found {len(spine_paths)} spine files. Starting export with {max_workers} workers...")
    start_time = time.time()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    tasks = []
    for spine_path in spine_paths:
        output_path = output
        # Generate folder structure based on .spine filename
        if output_path is not None:
            base_name = os.path.splitext(os.path.basename(spine_path))[0]
            output_path = os.path.join(output_path, base_name)
        task = executor.submit(export_spine, spine_exec, export_json, spine_path, output_path, base_path)
        tasks.append(task)

    completed = 0
    for _ in concurrent.futures.as_completed(tasks):
        completed += 1
        elapsed_time = time.time() - start_time
        minutes = math.floor(elapsed_time / 60)
        seconds = elapsed_time % 60
        print(f"Completed {completed}/{len(tasks)} time={minutes:02d}:{seconds:05.2f}")
    executor.shutdown()


def get_png_resolution(filename):
    image = Image.open(filename)
    width, height = image.size
    return width, height


def main():
    spine_exec = "/Applications/Spine.app/Contents/MacOS/Spine"

    parser = argparse.ArgumentParser(description='Process a .spine file and export it using Spine')
    parser.add_argument('input_file', type=str, help='Path to the input .spine file or '
                                                     'root folder to look for .spine files')
    parser.add_argument('--output', type=str, help='Output path. If not exists it will be created.')
    parser.add_argument('--spine_exec', type=str, help='Path to the Spine executable. Defaults to '
                                                       '/Applications/Spine.app/Contents/MacOS/Spine')
    parser.add_argument('--threads', type=int, help='Number of threads to use. Defaults to number of cores.')
    parser.add_argument('--export_json', type=str, help='Path to the export.json file. Defaults to "export.json"')
    args = parser.parse_args()

    if args.spine_exec is not None:
        spine_exec = args.spine_exec

    num_cores = multiprocessing.cpu_count()
    if args.threads is not None:
        num_cores = args.threads

    export_json = "export.json"
    if args.export_json is not None:
        export_json = args.export_json

    if not os.path.exists(export_json):
        print(f"export.json not found at '{export_json}'")
        exit(1)

    spine_paths = []
    if not os.path.splitext(args.input_file)[1]:
        for dirpath, dirnames, filenames in os.walk(args.input_file):
            for filename in filenames:
                if filename.endswith('.spine'):
                    file_path = os.path.join(dirpath, filename)
                    spine_paths.append(file_path)

        run_export_in_threads(spine_paths, args.output, spine_exec, export_json, args.input_file, num_cores)
    else:
        export_spine(spine_exec, export_json, args.input_file, args.output)


if __name__ == "__main__":
    main()
