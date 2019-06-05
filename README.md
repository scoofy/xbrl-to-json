# xbrl-to-json
Simple Python3 program to convert SEC XBRL datafiles to JSON format

to run at the current iteration, you'll need the ticker and the CIK, and folder name, then simply run:

xbrl_to_json.main_xbrl_to_json_converter(ticker, cik, foldername)

I used the anytree node module because it deals with a lot of the inherent problems between markup xbrl and key,value json.

Note, this program converts anytree tree structure into json, but it's readable, and the tree structure is usable in python for purposes.

I'll be expaning an api soon to work with wxstocks.