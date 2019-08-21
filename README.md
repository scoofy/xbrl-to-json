# xbrl-to-json
Simple Python3 program to convert SEC XBRL datafiles to JSON format

to run at the current iteration, you'll need the ticker and the CIK, and form type, then simply run:

xbrl_to_json.main_download_and_convert(ticker, cik, form_type)

I used the anytree node module because it deals with a lot of the inherent problems between markup xbrl and key,value json.

Finally, the program outputs a json file of the facts in nested dictionaries of their nodes.

-------------------------------------------

Note, this program converts anytree tree node structure into json, the fact dict is incomplete, but the node tree is complete, it's readable, and the tree structure is usable in python for purposes.

It will also output a text file with the visual representation of the anytree node structure.

I'll put in controls to shut that off at some point.