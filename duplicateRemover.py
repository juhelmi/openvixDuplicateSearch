#!/bin/python

import os
import sys
import re
import json
import argparse
# import io
import glob
import csv
from copy import deepcopy
import subprocess
import time

# Requires movie directory by default, mandatory argument
# Target is that command line argument overrides config_file settings.
parser = argparse.ArgumentParser()
parser.add_argument("directory", help="Directory for recordings. The directory contains .ts and .ts.meta files. Default json configuration is stored to there also.", type=str, default="/mnt/hdd/movie/")
parser.add_argument("-config_file", help="Full path and file name for configuration file.", default=".")
parser.add_argument("-p", "--print_duplicates", help="Print only record names to be deleted. On error there could be other print outs.")
parser.add_argument("-v", "--verbose", help="Give processing information, debugging mode. Adds extra prints for print_duplicates also",
                    action='store_true')
parser.add_argument("-d", "--delete_duplicates", help="Show only duplicates with 0. Delete with 1. Overrides config_file setting.")
parser.add_argument("-l", "--log_write_enabled", help="Set log writing status, 0 or 1")
# External process could be find combined with grep
# In practice this could be after json: -d 0 -v -s "find . -mmin +120 -maxdepth 2 -name '*.ts.meta'|grep -v .Trash"
parser.add_argument("-s", "--stream", help="Get file list from other process stream")
parser.add_argument("-i", "--stdin", help="Read filenames from pipe/stdin",
                    action='store_true')
parser.add_argument("-w", "--write_config", help="Write current arguments to json config file. First directory argument and config_file not written there",
                    action='store_true')
args = parser.parse_args()

# Log contains list of record dates. Contains used index, result of duplicate test, filename, meta title and description, file size
csv_log = []
log_fieldnames = ['index', 'result', 'dupl_inx', 'filename', 'line2', 'line3', 'file_size']
log_write_enabled = True
default_config_name = "duplicate_config.json"
meta_file_extension = r"[.]ts[.]meta$"     # Use regex format

def string_without_extension(s):
    return re.sub(meta_file_extension, '', s)

def get_filelist_for_folder(folder, subfoldesrs_also=True):
    """
    Search all files in given folder and below it
    :param folder: Name of folder to look files
    :param subfoldesrs_also: Optionally skip subfolder search
    :return: List of filenames.
    """
    result = []
    if not os.path.isdir(folder):
        if os.path.isfile(folder):
            result.append(folder)
    else:
        files = os.listdir(folder)
        for f in files:
            sub_file = folder +"/"+ f
            if not os.path.isdir(sub_file):
                result.append(sub_file)
            else:
                sub_list = get_filelist_for_folder(sub_file, subfoldesrs_also)
                result.extend(sub_list)
    return result


class DuplicateFinder:
    def __init__(self, movie_root, config_file):
        self.movie_path = movie_root
        # self.config = config_file

        # Read configuration
        if config_file == ".":
            config_filename = default_config_name
        else:
            config_filename = args.config_file
        json_data = '''
        { 
            "skipped_titles": [ 
                "[.]Trash[/]",
                "[Uu]utiset",
                "Ylen aamu",
                " Pilanp..?iten"
            ],
            "files_searched": [
                "[.]ts[.]meta$"
            ],
            "file_size_factor": "0.90",
            "use_empty_epg_description": "0",
            "delete_duplicates": "0",
            "include_subfolders": "1",
            "print_duplicates": "1",
            "verbose": "0",
            "read_from_stdin": 0,
            "process_string": "",
            "log_write_enabled": "1"
        }
        '''
        # First check if config_duplicates.json is in default directory. Write default when none exists
        if not os.path.exists(config_filename):
            data1 = json.loads(json_data)
            out_file = open(config_filename, "w")
            json.dump(data1, out_file, indent=2)
            out_file.close()

        with open(config_filename) as f:
            config = json.load(f)

        try:
            self.must_have_patterns = config['files_searched']
            self.skip_files_with_patterns = config['skipped_titles']
            # if factor value is 0.95 then last recording size must me at least 95 % of earlier maximum
            self.file_size_factor = float(config['file_size_factor'])
            self.delete_duplicates = bool(int(config['delete_duplicates']))
            self.use_empty_epg_description = bool(int(config['use_empty_epg_description']))
            self.log_write_enabled = bool(int(config['log_write_enabled']))
            self.include_subfolders = bool(int(config['include_subfolders']))  # includes also .Trash if not masked out
            self.print_duplicates = bool(int(config['print_duplicates']))   # Supress other debug prints when true
            self.verbose = bool(int(config['verbose']))
            self.process_string = config['process_string']
            self.read_from_stdin = bool(int(config['read_from_stdin']))
            self.forced_json_rewrite = False
        except KeyError as error:
            print(f"Config file is missing key, error in ḱey: {error}")
            print(f"Fix error in file: {config_filename} or delete it and it will be created again")
            sys.exit(3)

        if args.verbose:
            self.verbose = bool(int(args.verbose))
        if args.log_write_enabled:
            self.log_write_enabled = bool(int(args.log_write_enabled))
        if args.print_duplicates:
            self.print_duplicates = bool(int(args.print_duplicates))
        if args.delete_duplicates:
            self.delete_duplicates = bool(int(args.delete_duplicates))
        if args.stream or type(args.stream) is str:
            self.process_string = args.stream
        if args.stdin:
            self.read_from_stdin = True
            if len(self.process_string) > 0:
                print(f"Note: not calling read from other process as stdin read is defined.")
                self.process_string = ""

        if args.write_config:
            config['process_string'] = self.process_string
            config['read_from_stdin'] = False   # If there will be argument set to false then current value could be stored
            config['verbose'] = self.verbose
            config['print_duplicates'] = self.print_duplicates
            config['delete_duplicates'] = self.delete_duplicates
            config['log_write_enabled'] = self.log_write_enabled
            #config['log_write_enabled'] = self.log_write_enabled
            # Update this when new arguments are added and those are written to conf file
            with open(config_filename, "w") as fp:
                json.dump(config, fp, indent=2)

        os.chdir(self.movie_path)
        self.meta_files = []
        self.meta_texts = []

        self.files_suggested_to_be_removed = []
        self.files_suggested_to_be_kept = []
        self.files_skipped_by_pattern = []

    def _write_csv_log(self):
        if log_write_enabled:
            for name in self.files_skipped_by_pattern:
                csv_log.append({'filename': name, 'index': -1, 'result': "-"})
            with open('duplicate_search_log.csv', 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=log_fieldnames)
                writer.writeheader()
                writer.writerows(csv_log)

    # Filename processing first
    def _get_files_for_checking(self):
        # List of files to search duplicates
        try:
            self.all_files = os.listdir(self.movie_path)
            # Recursive search could be done but only first level is currently checked
            found_sub_dirs = []
            for dir_test in self.all_files:
                sub_dir = self.movie_path+"/"+dir_test
                # Search could be limited to one folder level if subfolders are not used when value is False
                # if self.include_subfolders and os.path.isdir(sub_dir):
                if os.path.isdir(sub_dir):
                    self.all_files.extend(get_filelist_for_folder(sub_dir, self.include_subfolders))
        except OSError as error:
            print(f"File list cannot be read, {error}")
            print(f"Given movie directory is {movie_root}")
            sys.exit(1)

        set_of_selections = set()
        if len(self.must_have_patterns) > 0:
            # Add all files to set
            for pattern in self.must_have_patterns:
                p = re.compile(pattern)
                for name in self.all_files:
                    if p.search(name):
                        set_of_selections.add(name)
        # print(set_of_selections)
        if len(self.must_have_patterns) > 0:
            # all_files = list(set_of_selections)
            self.all_files = [item for item in set_of_selections]
            self.all_files.sort()

        # Remove some records from list according to pattern
        for pattern_text in self.skip_files_with_patterns:
            pattern = re.compile(pattern_text)
            # for name in all_files:
            for inx in range(len(self.all_files)-1, -1, -1):
                name = self.all_files[inx]
                if pattern.search(name):
                    self.all_files.remove(name)
                    # print(f"Skips {name}")
                    self.files_skipped_by_pattern.append(name)
        if len(self.all_files) < 2:
            print(f"Check path for directory as there are not enough files.")
            return


    def _get_files_via_process(self):
        # Simple as all lines are filenames with full path

        start = time.time()
        process = subprocess.Popen(self.process_string, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
        output, error = process.communicate()

        t = time.time() - start
        if self.verbose:
            print(f"Elapsed time {t} for process {self.process_string}")
        if error != "":
            print(f"Errors found: {error}")
            sys.exit(2)
        self.all_files = []
        p = re.compile(meta_file_extension)
        first_non_meta = False
        for f in output.split('\n'):
            if p.search(f):
                self.all_files.append(f)
            else:
                if not first_non_meta:
                    first_non_meta = True
                    print(f"Error first not meta filename in given process output is '{f}'.\nRest are skipped.")
        if self.all_files[-1] == '':
            del self.all_files[-1]

    def _get_files_from_stdin(self):
        self.all_files = []
        p = re.compile(meta_file_extension)
        for line in sys.stdin:
            if line.strip() == '':
                break
            if not p.search(line):
                print(f"Error: line do not have meta file extension. Rest lines are skipped. Line: {line}")
                break;
            self.all_files.append(line.strip())

    def _collect_meta_data(self):
        # file count and positions are fixed. Start also log collection

        for inx, f in enumerate(self.all_files):
            pathname, extension = os.path.splitext(f)
            name = f.split('.')
            rec_dict = {'filename': f, 'index': inx, 'result': False}
            if len(name) >= 3 and name[-2] == 'ts' and name[-1] == 'meta':
                self.meta_files.append(pathname)
                #print(f"{name[-3]} added and ext: {name[-2]+'.'+name[-1]}")
                name_parts = name[-3].split(' - ')
                # Skipping of record could be done here
                # TO be done
                # Checks that name has all parts
                if len(name_parts) >= 3:
                    #print(f"Date: {name_parts[-3]} Channel: {name_parts[-2]} Title: {name_parts[-1]}")
                    with open(f) as text_file:
                        #print(f"Reading {f}")
                        _ = text_file.readline()
                        line2 = text_file.readline().strip()
                        line3 = text_file.readline().strip()
                        self.meta_texts.append((f, name_parts, line2, line3))
                        rec_dict['line2'] = line2
                        rec_dict['line3'] = line3
                else:
                    self.meta_texts.append((f, name_parts, "", ""))
                    # print(f"{f} skipped. Ext is {extension}")
            else:
                self.meta_texts.append((f, [pathname, "", ""], "", ""))
            csv_log.append(rec_dict)

    def _find_duplicates(self):
        # Compare if same Title and contents is found from records
        # size of meta_texts will change
        self.found_duplicates = []
        for meta_index in range(len(self.meta_texts)):
            meta_data = self.meta_texts[meta_index]
            first_found = False
            for cmp_index in range(meta_index+1, len(self.meta_texts)):
                if self.use_empty_epg_description == False and meta_data[3] == "":
                    # print(f"Empty description for {all_files[meta_index]} tile {meta_data[2]}")
                    continue
                if meta_data[2] == self.meta_texts[cmp_index][2] and meta_data[3] == self.meta_texts[cmp_index][3]:
                    # print(f"Duplicate at {meta_index} cmp_inx: {cmp_index} {first_found} Title: {meta_data[2]} Content: {meta_data[3]}")
                    # meta_texts[meta_index][4] = cmp_index
                    if not first_found:
                        self.found_duplicates.append([meta_index, cmp_index])
                        first_found = True
                    else:
                        last_list = self.found_duplicates[-1]
                        last_list.append(cmp_index)
                        self.found_duplicates[-1] = last_list
                    # break

        if self.verbose:
            print(f"Found {len(self.found_duplicates)} duplicates\n{self.found_duplicates}")
        # Nested list copied
        self.cleaned_duplicates = deepcopy( self.found_duplicates )

        # Find all records that are listed multiple times
        inx = 0
        while inx < len(self.cleaned_duplicates):
            rec = self.cleaned_duplicates[inx]
            dup_inx = inx + 1
            rec_inx = 1
            while dup_inx < len(self.cleaned_duplicates):
                # Last element in rec do not make duplicate alone. Do not search duplicates for it.
                if rec_inx < len(rec)-1 and rec[rec_inx] == self.cleaned_duplicates[dup_inx][0]:
                    del self.cleaned_duplicates[dup_inx]
                    rec_inx += 1
                else:
                    dup_inx += 1
            inx += 1

        if self.verbose:
            print(f"Cleaned duplicates {len(self.cleaned_duplicates)} duplicates\n{self.cleaned_duplicates}\n")
        # Search biggest file and select it if bigger than last one. Marginal in comparison is 1%
        file_sizes=[-1 for i in range(len(self.all_files))]
        for dupl_inx, dupl_list in enumerate(self.cleaned_duplicates):
            sizes = []
            max_value = 0
            max_inx = 0
            for inx, file_inx in enumerate(dupl_list):
                name = self.all_files[file_inx]
                pathname, extension = os.path.splitext(name)    # drop .meta extension from .ts.meta
                try:
                    size_of_file = file_sizes[file_inx]
                    if size_of_file <= 0:
                        stat_of_file = os.stat(pathname)
                        size_of_file = stat_of_file.st_size
                        file_sizes[file_inx] = size_of_file
                        csv_log[file_inx]['file_size'] = size_of_file
                    else:
                        # print(f"Size known {file_inx} {all_files[file_inx]}")
                        pass
                except FileNotFoundError as error:
                    size_of_file = 0
                sizes.append(size_of_file)
                if size_of_file >= max_value:
                    max_value = size_of_file
                    max_inx = inx
            if max_inx != len(dupl_list)-1:
                if max_value*self.file_size_factor > sizes[-1]*1.0:
                    # swap last and value in max_inx
                    tmp = self.cleaned_duplicates[dupl_inx][max_inx]
                    self.cleaned_duplicates[dupl_inx][max_inx] = self.cleaned_duplicates[dupl_inx][-1]
                    self.cleaned_duplicates[dupl_inx][-1] = tmp

        # Set to log status for duplicate indexes
        for dupl_list in self.cleaned_duplicates:
            for inx, value in enumerate(dupl_list):
                # last index is kept on place
                if 'dupl_inx' in csv_log[value]:
                    print(f"Internal error in cleaned_duplicates csv_log[value]['dupl_inx'] already has {csv_log[value]['dupl_inx']}, inx={value}")
                if inx < len(dupl_list)-1:
                    csv_log[value]['dupl_inx'] = "- "+str(dupl_list)
                else:
                    csv_log[value]['dupl_inx'] = "+ " + str(dupl_list)

    def _collect_removal_status(self ):
        # Print all removals

        for meta_index in range(len(self.meta_texts)):
            meta_data = self.meta_texts[meta_index]
            # Search current meta_index from rest of cleaned duplicates. Last index is to be kept.
            skip_this_index = False
            i = 0
            while not skip_this_index and i < len(self.cleaned_duplicates):
                j = 0
                while not skip_this_index and j < len(self.cleaned_duplicates[i])-1:
                    if self.cleaned_duplicates[i][j] == meta_index:
                        skip_this_index = True
                        # print(f"{meta_index} Skips {meta_data[2]} {meta_data[3]}")
                        # print(f"{meta_index} {file_sizes[meta_index]} name:{all_files[meta_index]}")
                        self.files_suggested_to_be_removed.append(self.all_files[meta_index])
                        csv_log[meta_index]['result'] = True
                        # found_duplicates.remove(meta_index)
                        if len(self.cleaned_duplicates[i]) > 2:
                            del self.cleaned_duplicates[i][j]    # When more than two copies found skip files one by one until two left
                        else:
                            del self.cleaned_duplicates[i]
                    else:
                        j += 1
                i += 1
            if not skip_this_index:
                # print(f"{meta_index} Keeps {meta_data[2]} {meta_data[3]}")
                # print(f"{meta_index} {file_sizes[meta_index]} name:{all_files[meta_index]}")
                self.files_suggested_to_be_kept.append(self.all_files[meta_index])

    def _do_the_duplicate_removal(self):
        # Print "Good" records
        if not self.print_duplicates or self.verbose:
            print(f"Keep following records, count {len(self.files_suggested_to_be_kept)}")
            for f in self.files_suggested_to_be_kept:
                print(string_without_extension(f))

        if not self.print_duplicates or self.verbose:
            print(f"\nTo be removed records, count {len(self.files_suggested_to_be_removed)}")
        for rec in self.files_suggested_to_be_removed:
            record_name = string_without_extension(rec)
            if self.verbose or self.print_duplicates:
                print(record_name)
            # When printing is selected then no actual removal is not done
            if self.delete_duplicates or not self.print_duplicates:
                for f in glob.glob(record_name + ".*"):
                    if self.verbose:
                        print(f"Removes: {f}")
                    os.remove(f)
        self._write_csv_log()

    def process_the_data(self):
        if self.read_from_stdin:
            self._get_files_from_stdin()
        elif len(self.process_string) > 0:
            self._get_files_via_process()
        else:
            self._get_files_for_checking()
        self._collect_meta_data()
        self._find_duplicates()
        self._collect_removal_status()
        self._do_the_duplicate_removal()

duplicate_worker = DuplicateFinder(args.directory, args.config_file)
duplicate_worker.process_the_data()
