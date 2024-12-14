#!/bin/python

import os
import sys
import re
import json
# import io
import glob
import csv
from copy import deepcopy

def string_without_extension(s):
    return re.sub(r"[.]ts[.]meta$", '', s)


# List of files to search duplicates
path = "/mnt/win_share/movie"
try:
    all_files = os.listdir(path)
except OSError as error:
    print(f"File list cannot be read, {error}")
    sys.exit("Digibox might be down, or atleast no connection")
os.chdir(path)
meta_files = []
meta_texts = []

files_suggested_to_be_removed = []
files_suggested_to_be_kept = []
files_skipped_by_pattern = []
# Log contains list of record dates. Contains used index, result of duplicate test, filename, meta title and description, file size
csv_log = []
log_fieldnames = ['index', 'result', 'dupl_inx', 'filename', 'line2', 'line3', 'file_size']
log_write_enabled = True

def write_csv_log():
    if log_write_enabled:
        for name in files_skipped_by_pattern:
            csv_log.append({'filename': name, 'index': -1, 'result': "-"})
        with open('duplicate_search_log.csv', 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=log_fieldnames)
            writer.writeheader()
            writer.writerows(csv_log)

# Read configuration
config_filename = "duplicate_config.json"
json_data = '''
{ 
    "skipped_titles": [ 
        "[Uu]utiset",
        "Ylen aamu",
        " Pilanp..?iten"
    ],
    "files_searched": [
        "[.]ts[.]meta$"
    ],
    "file_size_factor": "0.95",
    "use_empty_epg_description": "1",
    "delete_duplicates": "0",
    "log_write_enabled": "1"
}
'''
# First check if config_duplicates.json is in default directory. Write default when none exists
#if os.path.exists(config_filename):
#    os.remove(config_filename)
if not os.path.exists(config_filename):
    data1 = json.loads(json_data)
    out_file = open(config_filename, "w")
    json.dump(data1, out_file, indent=2)
    out_file.close()

with open(config_filename) as f:
    config = json.load(f)

must_have_patterns = config['files_searched']
skip_files_with_patterns = config['skipped_titles']
# if factor value is 0.95 then last recording size must me at least 95 % of earlier maximum
file_size_factor = float(config['file_size_factor'])
delete_duplicates = bool(int(config['delete_duplicates']))
use_empty_epg_description = bool(int(config['use_empty_epg_description']))
log_write_enabled = bool(int(config['log_write_enabled']))

# Filename processing first

set_of_selections = set()
if len(must_have_patterns) > 0:
    # Add all files to set
    for pattern in must_have_patterns:
        p = re.compile(pattern)
        for name in all_files:
            if p.search(name):
                set_of_selections.add(name)
# print(set_of_selections)
if len(must_have_patterns) > 0:
    # all_files = list(set_of_selections)
    all_files = [item for item in set_of_selections]
    all_files.sort()

# Remove some records from list according to pattern
for pattern_text in skip_files_with_patterns:
    pattern = re.compile(pattern_text)
    # for name in all_files:
    for inx in range(len(all_files)-1, -1, -1):
        name = all_files[inx]
        if pattern.search(name):
            all_files.remove(name)
            # print(f"Skips {name}")
            files_skipped_by_pattern.append(name)

# file count and positions are fixed. Start also log collection

for inx, f in enumerate(all_files):
    pathname, extension = os.path.splitext(f)
    name = f.split('.')
    rec_dict = {'filename': f, 'index': inx, 'result': False}
    if len(name) >= 3 and name[-2] == 'ts' and name[-1] == 'meta':
        meta_files.append(pathname)
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
                meta_texts.append((f, name_parts, line2, line3))
                rec_dict['line2'] = line2
                rec_dict['line3'] = line3
    else:
        # print(f"{f} skipped. Ext is {extension}")
        pass
    csv_log.append(rec_dict)

# Compare if same Title and contents is found from records
# size of meta_texts will change
found_duplicates = []
for meta_index in range(len(meta_texts)):
    meta_data = meta_texts[meta_index]
    first_found = False
    for cmp_index in range(meta_index+1, len(meta_texts)):
        if use_empty_epg_description == False and meta_data[3] == "":
            # print(f"Empty description for {all_files[meta_index]} tile {meta_data[2]}")
            continue
        if meta_data[2] == meta_texts[cmp_index][2] and meta_data[3] == meta_texts[cmp_index][3]:
            # print(f"Duplicate at {meta_index} cmp_inx: {cmp_index} {first_found} Title: {meta_data[2]} Content: {meta_data[3]}")
            # meta_texts[meta_index][4] = cmp_index
            if not first_found:
                found_duplicates.append([meta_index, cmp_index])
                first_found = True
            else:
                last_list = found_duplicates[-1]
                last_list.append(cmp_index)
                found_duplicates[-1] = last_list
            # break

print(f"Found {len(found_duplicates)} duplicates\n{found_duplicates}")
# Nested list copied
cleaned_duplicates = deepcopy( found_duplicates )

# Find all records that are listed multiple times
inx = 0
while inx < len(cleaned_duplicates):
    rec = cleaned_duplicates[inx]
    dup_inx = inx + 1
    rec_inx = 1
    while dup_inx < len(cleaned_duplicates):
        # Last element in rec do not make duplicate alone. Do not search duplicates for it.
        if rec_inx < len(rec)-1 and rec[rec_inx] == cleaned_duplicates[dup_inx][0]:
            del cleaned_duplicates[dup_inx]
            rec_inx += 1
        else:
            dup_inx += 1
    inx += 1

print(f"Cleaned duplicates {len(cleaned_duplicates)} duplicates\n{cleaned_duplicates}\n")
# Search biggest file and select it if bigger than last one. Marginal in comparison is 1%
file_sizes=[-1 for i in range(len(all_files))]
for dupl_inx, dupl_list in enumerate(cleaned_duplicates):
    sizes = []
    max_value = 0
    max_inx = 0
    for inx, file_inx in enumerate(dupl_list):
        name = all_files[file_inx]
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
        if max_value*1.0 > sizes[-1]*file_size_factor:
            # swap last and value in max_inx
            tmp = cleaned_duplicates[dupl_inx][max_inx]
            cleaned_duplicates[dupl_inx][max_inx] = cleaned_duplicates[dupl_inx][-1]
            cleaned_duplicates[dupl_inx][-1] = tmp

# Set to log status for duplicate indexes
for dupl_list in cleaned_duplicates:
    for inx, value in enumerate(dupl_list):
        # last index is kept on place
        if 'dupl_inx' in csv_log[value]:
            print(f"Internal error in cleaned_duplicates csv_log[value]['dupl_inx'] already has {csv_log[value]['dupl_inx']}, inx={value}")
        if inx < len(dupl_list)-1:
            csv_log[value]['dupl_inx'] = "- "+str(dupl_list)
        else:
            csv_log[value]['dupl_inx'] = "+ " + str(dupl_list)

# Print all removals

for meta_index in range(len(meta_texts)):
    meta_data = meta_texts[meta_index]
    # Search current meta_index from rest of cleaned duplicates. Last index is to be kept.
    skip_this_index = False
    i = 0
    while not skip_this_index and i < len(cleaned_duplicates):
        j = 0
        while not skip_this_index and j < len(cleaned_duplicates[i])-1:
            if cleaned_duplicates[i][j] == meta_index:
                skip_this_index = True
                # print(f"{meta_index} Skips {meta_data[2]} {meta_data[3]}")
                # print(f"{meta_index} {file_sizes[meta_index]} name:{all_files[meta_index]}")
                files_suggested_to_be_removed.append(all_files[meta_index])
                csv_log[meta_index]['result'] = True
                # found_duplicates.remove(meta_index)
                if len(cleaned_duplicates[i]) > 2:
                    del cleaned_duplicates[i][j]    # When more than two copies found skip files one by one until two left
                else:
                    del cleaned_duplicates[i]
            else:
                j += 1
        i += 1
    if not skip_this_index:
        # print(f"{meta_index} Keeps {meta_data[2]} {meta_data[3]}")
        # print(f"{meta_index} {file_sizes[meta_index]} name:{all_files[meta_index]}")
        files_suggested_to_be_kept.append(all_files[meta_index])

# Print "Good" records
print(f"Keep following records, count {len(files_suggested_to_be_kept)}")
for f in files_suggested_to_be_kept:
    print(string_without_extension(f))

print(f"\nTo be removed records, count {len(files_suggested_to_be_removed)}")
for rec in files_suggested_to_be_removed:
    record_name = string_without_extension(rec)
    print(record_name)
    if delete_duplicates:
        for f in glob.glob(record_name + ".*"):
            # print(f"Removes: {f}")
            os.remove(f)

write_csv_log()

