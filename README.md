# openvixDuplicateSearch
Search and remove duplicate recordings acccording to meta files

Tool is in development phase and use on your own risk. If there are valuable recordings make backup before running duplicate search.

Currently this searches config file from /mnt/win_share/movie. Meaning that digibox disk is mounted to Linux and python script run at there. Target is to run later on OpenVix. 

script demo run command could look like "python duplicateRemover /mnt/win_share/movie -config_file /home/juha/tmp/dup_conf.json -d 0 -v -l 1" in that case actual removal will not be do. It shows on screen record status and writes log file what was status in duplicate seach.

Remove command could be "python duplicateRemover /mnt/win_share/movie -config_file /home/juha/tmp/dup_conf.json -d 1 -l 1". If log is not wanted then change "-l 1" to "-l 0".

When openVix is started/rebooted during recording continued recordings are chacked acccording to first part of recording. If there is duplicate in such case typically file with recording_name.ts and recording_name_001.ts will be deleted. Feature still to be checked with more practical cases.

Tested platform is OpenVix 6.6.13 and Ubuntu 24.04. Vu+ Solo SE V2 running OpenVix.

Documentation to be written better when script is tested better. 
