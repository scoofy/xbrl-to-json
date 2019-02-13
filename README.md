# xbrl-to-json
Simple Python3 program to download and convert SEC XBRL datafiles to JSON format

Firstly, and most importantly, there is significant work to be done regarding large text data:

Look for this block of code in the function: convert_xbrl_tree_and_ns_to_dict()

        for context_element in context_ref_list:
            # these text attributes are a mess, so i ignore them
            if "TextBlock" in str(context_element.tag):
                continue
            elif "&lt;" in str(context_element.text):
                continue
            elif "<div " in str(context_element.text) and "</div>" in str(context_element.text):
                continue

I haven't sorted that out, but otherwise, it should extract data very well. I would appreciate it if someone could try it out and let me know if you get any errors.

to run at the current iteration, you'll need the ticker and the CIK, then simply run:

xbrl_to_json.xbrl_to_json(ticker, cik)

to get the latest 10-K. If you want to be more specific with form-type and date, here are some different arguments you can pass:

xbrl_to_json.xbrl_to_json(
    ticker,
    cik,
    form_type = "10-K",
    year = None,
    month = None,
    day = None,
    )

