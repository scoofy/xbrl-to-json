import os, logging, datetime, json
import urllib.request
import bs4
import xml.etree.ElementTree as ET

def return_url_request_data(url, values_dict={}, secure=False):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_2) AppleWebKit/601.3.9 (KHTML, like Gecko) Version/9.0.2 Safari/601.3.9"}
    http__prefix = "http://"
    https_prefix = "https://"
    if secure:
        url_prefix = https_prefix
    else:
        url_prefix = http__prefix
    if "http://" in url or "https://" in url:
        url_prefix = ""
    url = url_prefix + url
    encoded_url_extra_values = urllib.parse.urlencode(values_dict)
    data = encoded_url_extra_values.encode('utf-8')
    #logging.warning("\n{}\n{}\n{}".format(url, data, headers))
    if data:
        request = urllib.request.Request(url, data, headers=headers)
    else:
        request = urllib.request.Request(url, headers=headers)
    response = urllib.request.urlopen(request) # get request
    response_data = response.read().decode('utf-8')
    return response_data

def sec_xbrl_single_stock(cik, form_type):
    base_url = "https://www.sec.gov/cgi-bin/browse-edgar"
    values =   {"action": "getcompany",
                "CIK": cik,
                "type": form_type,
                }
    response_data = return_url_request_data(base_url, values, secure=True)
    return response_data

def parse_sec_results_page(sec_response_data, date="most recent"):
    soup = bs4.BeautifulSoup(sec_response_data, 'html.parser')
    table_list = soup.find_all("table", {"summary": "Results"})
    #print(len(table_list))
    if not len(table_list) == 1:
        logging.error("something's up here")
    table = table_list[0]
    document_button_list = table.find_all("a", {"id":"documentsbutton"})
    if date == "most recent":
        relevant_a_tag = table.find("a", {"id":"documentsbutton"})
    else:
        relevant_td = table.find_all("td", string="{}-{}-{}".format(year, month, day))
        relevant_td_parent = relevant_td.parent
        relevant_a_tag = relevant_td_parent.find("a", {"id":"documentsbutton"})
    relevant_a_href = relevant_a_tag['href']
    sec_url = "https://www.sec.gov"
    relevant_xbrl_url = sec_url + relevant_a_href
    return relevant_xbrl_url

def write_xbrl_file(file_name, sec_response_data):
    with open(file_name, 'w') as outfile:
        outfile.write(sec_response_data)

def get_xbrl_files_and_return_folder_name(xbrl_data_page_response_data):
    soup = bs4.BeautifulSoup(xbrl_data_page_response_data, 'html.parser')
    table_list = soup.find_all("table", {"summary": "Data Files"})
    if not len(table_list) == 1:
        logging.error("something's up here")
    table = table_list[0]
    a_tag_list = table.find_all("a")
    sec_url = "https://www.sec.gov"
    folder_name = None
    data_date = None
    for a in a_tag_list:
        href = a["href"]
        file_name = a.text
        if not folder_name:
            if "_" not in file_name:
                folder_name = file_name.split(".")[0]
                data_date = folder_name.split("-")[1]
        file_name = folder_name + "/" + file_name
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
        full_url = sec_url + href
        response_data = return_url_request_data(full_url)
        write_xbrl_file(file_name, response_data)
    return folder_name, data_date

def get_xbrl_filename_from_folder_name(folder_name):
    'get filename'
    return "{}/{}.xml".format(folder_name, folder_name)

def extract_xbrl_namespace_and_tree(xbrl_filename):
    ns = {}
    try:
        for event, (name, value) in ET.iterparse(xbrl_filename, ['start-ns']):
            if name:
                ns[name] = value
    except Exception as e:
        logging.error(e)
        return[None, None]
    tree = ET.parse(xbrl_filename)
    return [tree, ns]

def iso_date_to_datetime(date_str):
    'iso date to datetime'
    return datetime.date(int(date_str.split("-")[0]), int(date_str.split("-")[1]), int(date_str.split("-")[2]))

def convert_xbrl_tree_and_ns_to_dict(xbrl_tree, namespace, file_name, ticker, cik):
    DEFAULT_CONTEXT_TAG = "{http://www.xbrl.org/2003/instance}context"
    DEFAULT_ENTITY_TAG = "{http://www.xbrl.org/2003/instance}entity"
    DEFAULT_IDENTIFIER_TAG = "{http://www.xbrl.org/2003/instance}identifier"
    DEFAULT_PERIOD_TAG = "{http://www.xbrl.org/2003/instance}period"

    tree = xbrl_tree
    root = tree.getroot()
    ns = namespace
    reverse_ns = {v: k for k, v in ns.items()}
    # get CIK for stock, else return empty dict
    try:
        context_tag = tree.find(DEFAULT_CONTEXT_TAG, ns)
        entity_tag = context_tag.find(DEFAULT_ENTITY_TAG, ns)
        identifier_tag = entity_tag.find(DEFAULT_IDENTIFIER_TAG, ns)
        cik = identifier_tag.text
    except:
        logging.error('CIK could not be found for: {}'.format(file_name))
        return None

    context_element_list = None
    for identifier_tag in [DEFAULT_IDENTIFIER_TAG,
                           "xbrli:context",
                           "context",
                          ]:
        try:
            context_element_list = tree.findall(identifier_tag, ns)
        except:
            pass
        if context_element_list:
            break

    if not context_element_list:
        logging.info("Improperly formatted XBRL file. Will try to parse with common made errors...")
        potential_identifier_tag_list = []
        root = tree.getroot()
        logging.warning(root.tag)
        logging.warning(root.attrib)
        for child in root:
            if 'context' in child.tag:
                if child.tag not in potential_identifier_tag_list:
                    potential_identifier_tag_list.append(child.tag)
        for identifier_tag in potential_identifier_tag_list:
            context_element_list = tree.findall(identifier_tag)

    if not context_element_list:
        logging.error(context_element_list)
        logging.error(ns)
        logging.error("XBRL file could not be parsed: {}".format(file_name))
        sys.exit()
        return

    xbrl_stock_dict = {ticker: {}}

    for element in context_element_list:
        period_dict = dict()
        dimension = None
        dimension_value = None
        previous_entry = None
        # get period first:
        period_element = element.find(DEFAULT_PERIOD_TAG)
        for item in period_element.iter():
            # a lot of these datetimes have leading and trailing \n's
            formatted_item = str(item.text).strip().replace("\n", "")
            if "T" in formatted_item: # someone put time in the date str
                formatted_item = formatted_item.split("T")[0]
            if "startDate" in item.tag:
                period_dict["startDate"] = formatted_item
            elif "endDate" in item.tag:
                period_dict["endDate"] = formatted_item
            elif "instant" in item.tag:
                period_dict["instant"] = formatted_item
            elif "forever" in item.tag:
                period_dict["forever"] = formatted_item

        if not period_dict:
            logging.error("No period")
        else:
            # logging.warning(period_dict)
            pass

        # datetime YYYY-MM-DD
        datetime_delta = None
        if period_dict.get("startDate"):
            start_date = period_dict.get("startDate")
            end_date = period_dict.get("endDate")
            if start_date != end_date:
                period_serialized = end_date + ":" + start_date
            else:
                period_serialized = end_date
            start_datetime = iso_date_to_datetime(start_date)
            end_datetime = iso_date_to_datetime(end_date)
            datetime_delta = end_datetime - start_datetime
            datetime_to_save = end_datetime
            iso_date_to_save = end_date
            iso_start_date = start_date
        elif period_dict.get("instant"):
            instant = period_dict.get("instant")
            period_serialized = instant
            instant_datetime = iso_date_to_datetime(instant)
            datetime_to_save = instant_datetime
            iso_date_to_save = instant
        elif period_dict.get("forever"):
            forever = period_dict.get("forever")
            period_serialized = forever
            forever_datetime = iso_date_to_datetime(forever)
            datetime_to_save = forever_datetime
            iso_date_to_save = forever
        else:
            logging.error("no period_serialized")
            period_serialized = None
            datetime_to_save = None

        context_id = element.get("id")
        context_ref_list = [x for x in root if x.get("contextRef") == context_id]
        for context_element in context_ref_list:
            # these text attributes are a mess, so i ignore them
            if "TextBlock" in str(context_element.tag):
                continue
            elif "&lt;" in str(context_element.text):
                continue
            elif "<div " in str(context_element.text) and "</div>" in str(context_element.text):
                continue

            tag = context_element.tag
            split_tag = tag.split("}")
            if len(split_tag) > 2:
                logging.error(split_tag)
            institution = reverse_ns.get(split_tag[0][1:])
            accounting_item = split_tag[1]
            # lots of problems with new lines in this
            value = str(context_element.text).strip().replace("\n","")
            unitRef = context_element.get("unitRef")
            decimals = context_element.get("decimals")
            if not xbrl_stock_dict[ticker].get(institution):
                xbrl_stock_dict[ticker][institution] = {accounting_item: {period_serialized: {"value": value}}}
            elif xbrl_stock_dict[ticker][institution].get(accounting_item) is None:
                xbrl_stock_dict[ticker][institution][accounting_item] = {period_serialized: {"value": value}}
            else:
                xbrl_stock_dict[ticker][institution][accounting_item].update({period_serialized: {"value": value}})
            period_dict = xbrl_stock_dict[ticker][institution][accounting_item][period_serialized]
            period_dict.update({"datetime": iso_date_to_save})
            if datetime_delta:
                period_dict.update({"timedeltastart": iso_start_date})
            if unitRef:
                period_dict.update({"unitRef": unitRef})
            if decimals:
                period_dict.update({"decimals": decimals})
    return(xbrl_stock_dict)

def write_dict_as_json(xbrl_dict, ticker, data_date):
    with open('{}_xbrl_data_{}.json'.format(ticker, data_date), 'w') as outfile:
        json.dump(xbrl_dict, outfile, indent=4)

def xbrl_to_json(ticker, cik, form_type = "10-K", year = None, month = None, day = None):
    if year and month and day:
        date = "{}-{}-{}".format(year, month, day)
    else:
        date = "most recent"
    sec_response_data = sec_xbrl_single_stock(cik, form_type)
    relevant_xbrl_url = parse_sec_results_page(sec_response_data, date=date)
    xbrl_data_page_response_data = return_url_request_data(relevant_xbrl_url)
    folder_name, data_date = get_xbrl_files_and_return_folder_name(xbrl_data_page_response_data)
    xbrl_filename = get_xbrl_filename_from_folder_name(folder_name)
    xbrl_tree, namespace = extract_xbrl_namespace_and_tree(xbrl_filename)
    xbrl_dict = convert_xbrl_tree_and_ns_to_dict(xbrl_tree, namespace, xbrl_filename, ticker, cik)
    write_dict_as_json(xbrl_dict, ticker, data_date)

#if __name__ == "__main__":
#    testing_appl = False
#    if testing_appl:
#        xbrl_to_json("aapl", 320193)
