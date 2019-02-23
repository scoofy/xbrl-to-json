import sys, os, logging, datetime, json
import urllib.request
import bs4
import xml.etree.ElementTree as ET
import pprint as pp

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

def return_all_xbrl_context_element_tree_items(context_element_tree):
    list_to_return = []
    for item in context_element_tree:
        if len(item) > 1:
            return return_all_xbrl_context_element_tree_items(item)
        else:
            list_to_return.append(item)
    return list_to_return

total_count = 0
def elem_tree_recursive(root_elem, tag=None, count=0):
    elem = root_elem
    elem_dict = {}
    text = elem.text
    attrib = elem.attrib
    #elem_dict["tag"] = elem.tag
    if text and str(text).strip():
        elem_dict["text"] = text.strip()
    if attrib:
        elem_dict["attrib"] = attrib
    if len(list(elem)):
        children_list = []
        for index, child  in enumerate(list(elem)):
            child_dict = {child.tag: elem_tree_recursive(child, tag=child.tag, count = count + 1)}
            children_list.append(child_dict)
        elem_dict["children"] = children_list

    if tag == None:
        root_tag = elem.tag
        return {root_tag: elem_dict}
    else:
        return elem_dict



def convert_xbrl_tree_and_ns_to_dict(xbrl_tree, namespace, file_name, ticker, cik):
    DEFAULT_CONTEXT_TAG = "{http://www.xbrl.org/2003/instance}context"
    DEFAULT_ENTITY_TAG = "{http://www.xbrl.org/2003/instance}entity"
    DEFAULT_IDENTIFIER_TAG = "{http://www.xbrl.org/2003/instance}identifier"
    DEFAULT_PERIOD_TAG = "{http://www.xbrl.org/2003/instance}period"

    tree = xbrl_tree
    root = tree.getroot()
    tree = ET.parse(file_name)
    tree_dict = elem_tree_recursive(root)
    return tree_dict

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

"""
if __name__ == "__main__":
    testing_appl = False
    if testing_appl:
        ticker = 'aapl'
        cik = 320193
        apple_file_base_str = "aapl-20180929"
        file_type_list = [".xsd", "", "_cal", "_def", "_lab", "_pre"]
        for file_type in file_type_list:
            xbrl_filename = "{}/{}{}.xml".format(apple_file_base_str, apple_file_base_str, file_type)
            if file_type == ".xsd":
                xbrl_filename = xbrl_filename.replace(".xml", "")
            xbrl_tree, namespace = extract_xbrl_namespace_and_tree(xbrl_filename)
            xbrl_dict = convert_xbrl_tree_and_ns_to_dict(xbrl_tree, namespace, xbrl_filename, ticker, cik)
            write_dict_as_json(xbrl_dict, 'aapl-20180929/aapl-20180929{}'.format(file_type), "TEST")
"""