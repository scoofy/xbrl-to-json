import sys, os, logging, datetime, json, time, copy
import urllib.request
import bs4, anytree, anytree.exporter, anytree.importer
import xml.etree.ElementTree as ET
import pprint as pp
logging.basicConfig(format='  ---- %(filename)s|%(lineno)d ----\n%(message)s', level=logging.INFO)

clarks_to_ignore = ['http://www.w3.org/2001/XMLSchema',
                    'http://www.xbrl.org/2003/instance',
                    'http://www.xbrl.org/2003/linkbase',
                    'http://xbrl.org/2006/xbrldi',
                    ]
#official_node_attributes = ["attrib", "clark", "fact", "name", "node_order", "prefix", "suffix"]

prefixes_that_matter = set()

def main_xbrl_to_json_converter(ticker, cik, folder_name):
    extensions_list = [".xml",
                       ".xsd",
                       "_lab.xml",
                       "_def.xml",
                       "_pre.xml",
                       "_cal.xml",
                       ]
    root_node_dict = {}
    for extension in extensions_list:
        xbrl_filename = "{}/{}{}".format(folder_name, folder_name, extension)
        try:
            json_data = import_json(xbrl_filename)
            root_node = convert_dict_to_node_tree(json_data)
        except Exception as e:
            logging.error(e)
            logging.info("processing xbrl files")
            root_node = xbrl_to_json_processor(xbrl_filename)
            logging.info("done")
        root_node_dict[extension[1:]] = root_node
    collect_relevant_prefixes("{}/{}{}".format(folder_name, folder_name, extensions_list[0]))
    fact_tree_root = fact_centric_xbrl_processor(root_node_dict, ticker)
    xbrl_to_json_processor(folder_name + "_root_node", fact_tree_root)

def return_refernce_node(node, fact_tree_root, other_tree_root):
    fact_node = None
    locator = None
    href = node.attrib.get("{http://www.w3.org/1999/xlink}href")
    if href:
        locator = return_xlink_locator(node)
    else:
        if node.clark not in clarks_to_ignore:
            locator = node.suffix
    if locator:
        for prefix in prefixes_that_matter:
            if locator.startswith("{}_".format(prefix)):
                locator = locator.replace("{}_".format(prefix), "")
        '''this is a fact item'''
        fact_node = anytree.search.find_by_attr(fact_tree_root, locator)
        if not fact_node:
            fact_node = anytree.Node(locator,
                                     parent=fact_tree_root,
                                     suffix=locator)
        return fact_node
    else:
        '''this is a contextual item'''
        xbrli_node = anytree.search.find_by_attr(other_tree_root, "{{{}}}{}".format(node.clark, node.suffix))
        if not xbrli_node:
            xbrli_node = anytree.Node("{{{}}}{}".format(node.clark, node.suffix),
                                     parent=other_tree_root,
                                     suffix=node.suffix)
        return xbrli_node

def fact_centric_xbrl_processor(root_node_dict, ticker, sort_trash_for_debugging=False):
    fact_tree_root = anytree.Node(ticker)
    other_tree_root = anytree.Node('xbrli')
    trash_tree_root = anytree.Node('unsorted_trash')
    parent_child_tuple_list = []

    # here, we're just looking to see if a top level fact reference exists (could be made more efficient in the future, but limited)
    print("Start initial sorting:")
    start_time = time.time()
    for extension, root_node in root_node_dict.items():
        for node in anytree.PreOrderIter(root_node):
            try:
                suffix = node.suffix
            except:
                logging.error(node)
                pp.pprint(vars(node))
                sys.exit()

            # we create a refernce node if it doesn't exist, now let's pair it with that node
            reference_node = return_refernce_node(node, fact_tree_root, other_tree_root)
            parent_child_tuple_list.append((reference_node, node))

    for parent, child in parent_child_tuple_list:
        # now lets unite all these nodes together
        unique = True
        for existing_child in parent.children:
            if vars(child) == vars(existing_child):
                # this prevents lots of redundant nodes
                unique = False
            if unique == False:
                break
        if unique == True:
            # if we have a unique parent child relationship, we map it
            child.parent = parent

        else: # node is not unique
            child.parent = trash_tree_root
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    print("Finished in {}sec".format(round(time.time() - start_time)))


    # now let's see if we can pair more of the other refernces with our facts
    print("Start deep sorting:")
    start_time = time.time()
    fact_tree_children_dict = {node.suffix: node for node in fact_tree_root.children}
    for node in anytree.PreOrderIter(other_tree_root):
        replacement_parent = return_new_parent(node, fact_tree_children_dict)
        if replacement_parent:
            node.parent = replacement_parent
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    print("Finished in {}sec".format(round(time.time() - start_time)))



    #fact_tree_children_dict = {node.suffix: node for node in fact_tree_root.children}
    print("Start deep sorting second pass:")
    start_time = time.time()
    for node in anytree.PreOrderIter(other_tree_root):
        replacement_parent = return_new_parent_round_two(node, fact_tree_children_dict)
        if replacement_parent:
            node.parent = replacement_parent
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    print("Finished in {}sec".format(round(time.time() - start_time)))

    print("Convert context refs:")
    start_time = time.time()
    convert_context_refs_into_id_keyed_dict(fact_tree_root, other_tree_root, trash_tree_root)
    print("Finished in {}sec".format(round(time.time() - start_time)))


    if sort_trash_for_debugging:
        print("Sort trash file:")
        start_time = time.time()
        trash_tree_root = keep_trash_sorted(trash_tree_root)
        print("Finished in {}sec".format(round(time.time() - start_time)))


    print("Saving text files")
    start_time = time.time()
    fact_tree_root_filename = ticker + "_facts"
    root_node_to_rendertree_text_file(fact_tree_root, fact_tree_root_filename)
    other_tree_root_filename = ticker + "_xbrli"
    root_node_to_rendertree_text_file(other_tree_root, other_tree_root_filename)
    trash_filename = ticker + "_trash"
    root_node_to_rendertree_text_file(trash_tree_root, trash_filename)
    print("Finished in {}sec".format(round(time.time() - start_time)))

    return fact_tree_root


def convert_context_refs_into_id_keyed_dict(fact_tree_root, other_tree_root, trash_tree_root):
    context_node = None
    period_node_list = []
    for child in list(other_tree_root.children):
        if child.suffix == "context":
            context_node = child
        elif child.suffix in ["startDate", "endDate", "instant", "forever"]:
            period_node_list.append(child)

    context_dict = {}
    for period_node in period_node_list:
        for node in anytree.PreOrderIter(period_node):
            try:
                existing_entry = context_dict.get(node.parent_id)
            except:
                continue
            if node.parent.suffix == "measure":
                continue
            if existing_entry is None:
                context_dict[node.parent_id] = node.fact
            else: # entry already exists
                if node.suffix == "startDate":
                    new_entry = node.fact + ":" + existing_entry
                elif node.suffix == "endDate":
                    new_entry = existing_entry + ":" + node.fact
                elif node.suffix == "instant":
                    logging.error("this should not happen")
                    sys.exit()
                context_dict[node.parent_id] = new_entry
            node.parent = trash_tree_root
    for node in anytree.PreOrderIter(context_node):
        node.parent = trash_tree_root
    context_dict_node = anytree.Node("context_dict", parent=fact_tree_root, attrib = context_dict)






def keep_trash_sorted(trash_tree_root):
    sorted_trash_tree_root = anytree.Node('trash')
    for node in anytree.PreOrderIter(trash_tree_root):
        success = False
        if node.parent:
            for sorted_node in anytree.PreOrderIter(sorted_trash_tree_root):
                if sorted_node.parent:
                    if vars(node) == vars(sorted_node):
                        success = True
                        node.parent = sorted_node
                        break
            if not success:
                node.parent = sorted_trash_tree_root
    print("old trash tree")
    print(anytree.RenderTree(trash_tree_root))
    return sorted_trash_tree_root


def print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root):
    fact_tree_root_len = len(list(anytree.PreOrderIter(fact_tree_root)))
    other_tree_root_len = len(list(anytree.PreOrderIter(other_tree_root)))
    trash_tree_root_len = len(list(anytree.PreOrderIter(trash_tree_root)))
    print("facts:\t{}\tother:\t{}\ttrash:\t{}".format(fact_tree_root_len, other_tree_root_len, trash_tree_root_len))


def return_new_parent(node, fact_tree_children_dict):
    # step 1
    try:
        parent_id = node.parent_id
    except:
        parent_id = None
    if parent_id:
        parent = fact_tree_children_dict.get(parent_id)
        if parent:
            return parent
    # step 2
    try:
        dimension = node.attrib.get("dimension")
    except:
        dimension = None
    if dimension:
        dimension_parent_id = dimension.split(":")[-1]
        parent = fact_tree_children_dict.get(dimension_parent_id)
        if parent:
            return parent
        dimension_underscore = dimension.replace(":", "_")
        parent = fact_tree_children_dict.get(dimension_underscore)
        if parent:
            return parent
    # step 3
    try:
        label = node.attrib.get("{http://www.w3.org/1999/xlink}label")
    except:
        label = None

    if label:
        for suffix, tree_node in fact_tree_children_dict.items():
            if suffix in label:
                try:
                    parent_label = tree_node.attrib.get("{http://www.w3.org/1999/xlink}label")
                except:
                    parent_label = None
                if parent_label:
                    if label == parent_label:
                        return tree_node
                parent = recursive_label_node_getter(tree_node, label)
                if parent:
                    return parent

    try:
        from_attrib = node.attrib.get("{http://www.w3.org/1999/xlink}from")
        to_attrib = node.attrib.get("{http://www.w3.org/1999/xlink}to")
    except:
        from_attrib = None
        to_attrib = None
    if from_attrib and to_attrib:
        # to attribute (make copy)
        '''
        for suffix, tree_node in fact_tree_children_dict.items():
            if suffix in to_attrib:
                try:
                    parent_label = tree_node.attrib.get("{http://www.w3.org/1999/xlink}label")
                except:
                    parent_label = None
                if parent_label:
                    if to_attrib == parent_label:
                        to_node = copy.copy(node)
                        to_node.parent = tree_node
                        break
                to_parent = recursive_label_node_getter(tree_node, to_attrib)
                if to_parent:
                    to_node = copy.copy(node)
                    to_node.parent = tree_node
                    break
        '''
        # from attribute (return node)
        for suffix, tree_node in fact_tree_children_dict.items():
            if suffix in from_attrib:
                try:
                    parent_label = tree_node.attrib.get("{http://www.w3.org/1999/xlink}label")
                except:
                    parent_label = None
                if parent_label:
                    if from_attrib == parent_label:
                        return tree_node
                parent = recursive_label_node_getter(tree_node, from_attrib)
                if parent:
                    return parent
    # step 4
    try:
        role = node.attrib.get("{http://www.w3.org/1999/xlink}role")
    except:
        role = None
    if role:
        parent = fact_tree_children_dict.get(role.split("/")[-1])
        if parent:
            return parent

def return_new_parent_round_two(node, fact_tree_children_dict):
    look_up_list = ["name", "{http://www.w3.org/1999/xlink}from", "id"]
    for item in look_up_list:
        try:
            attribute = node.attrib.get(item)
        except:
            attribute = None
        if attribute:
            for suffix, tree_node in fact_tree_children_dict.items():
                if suffix == attribute:
                    return tree_node
                elif suffix in attribute:
                    parent = recursive_node_id_getter(tree_node, attribute)
                    if parent:
                        return parent
                    parent = recursive_label_node_getter(tree_node, attribute)
                    if parent:
                        return parent

def recursive_node_id_getter(node, original_id):
    try:
        potential_id_match = node.attrib.get("id")
    except:
        potential_id_match = None
    if potential_id_match:
        if original_id == potential_id_match:
            return node
    for child in node.children:
        parent = recursive_node_id_getter(child, original_id)
        if parent:
            return parent

def recursive_label_node_getter(node, original_label):
    try:
        potential_match = node.attrib.get("{http://www.w3.org/1999/xlink}label")
    except:
        potential_match = None
    if potential_match:
        if original_label == potential_match:
            return node
        if original_label == potential_match.replace("loc_", "lab_"):
            return node
    for child in node.children:
        parent = recursive_label_node_getter(child, original_label)
        if parent:
            return parent

def other_tree_node_replacement(attribute_list, fact_tree_root_children):
    replacement_node = None
    for child in fact_tree_root_children:
        for attribute in attribute_list:
            if attribute == child.suffix:
                replacement_node = child
            if replacement_node:
                return replacement_node
        if not replacement_node:
            for attribute in attribute_list:
                new_attr = attribute.replace(":", "_")
                if new_attr == child.suffix:
                    replacement_node = child
                if replacement_node:
                    return replacement_node
        if not replacement_node:
            for attribute in attribute_list:
                try:
                    new_attr = attribute.split(":")[-1]
                except:
                    continue
                if new_attr == child.suffix:
                    replacement_node = child
                if replacement_node:
                    return replacement_node
        if not replacement_node:
            for attribute in attribute_list:
                try:
                    new_attr = attribute.split("_")[-1]
                except:
                    continue
                if new_attr == child.suffix:
                    replacement_node = child
                if replacement_node:
                    return replacement_node
    return replacement_node

def collect_relevant_prefixes(xbrl_filename):
    tree, ns, root = extract_xbrl_tree_namespace_and_root(xbrl_filename)
    reversed_ns = {value: key for key, value in ns.items()}
    recursive_prefixes(root, reversed_ns)

def recursive_prefixes(xbrl_element, reversed_ns):
    clark, prefix, suffix = xbrl_clark_prefix_and_suffix(xbrl_element, reversed_ns)
    if clark not in clarks_to_ignore:
        if prefix not in prefixes_that_matter:
            prefixes_that_matter.add(prefix)
    for element in xbrl_element:
        recursive_prefixes(element, reversed_ns)


def xbrl_to_json_processor(xbrl_filename, root_node=None):
    json_dict = {}
    if not root_node:
        root_node = process_xbrl_file_to_tree(xbrl_filename)
    #print(anytree.RenderTree(root_node))
    flat_file_dict = convert_tree_to_dict(root_node)
    write_dict_as_json(flat_file_dict, xbrl_filename)
    root_node_to_rendertree_text_file(root_node, xbrl_filename)
    return root_node

def custom_render_tree(root_node):
    output_str = ""
    for pre, _, node in anytree.RenderTree(root_node):
        fact = ""
        formatted_fact = ""
        attrib = ""
        formatted_attrib = ""
        try:
            fact = node.fact
            attrib = node.attrib
        except:
            pass
        if fact:
            formatted_fact = "\n{}{}".format(pre, fact)
        if attrib:
            formatted_attrib = "\n{}{}".format(pre, attrib)
        formatted_str = "{}{}{}{}\n".format(pre, node.name, formatted_fact, formatted_attrib)
        output_str = output_str + "\n" + formatted_str
    return output_str

def root_node_to_rendertree_text_file(root_node, xbrl_filename, custom = False):
    with open('{}_render.txt'.format(xbrl_filename), 'w') as outfile:
            if custom:
                output_str = custom_render_tree(root_node)
            else:
                output_str = str(anytree.RenderTree(root_node))
            outfile.write(output_str)

def recursive_iter(xbrl_element, reversed_ns, parent=None, node_order=0):
    elements = []
    clark, prefix, suffix = xbrl_clark_prefix_and_suffix(xbrl_element, reversed_ns)
    fact = xbrl_element.text
    if isinstance(fact, str):
        fact = fact.strip()
    if fact is None:
        fact = ""
    attrib = xbrl_element.attrib
    parent_id = None
    if fact:
        try:
            parent_id = parent.attrib.get("id")
            if parent_id is None:
                if parent.suffix == "period":
                    grandparent = parent.parent
                    # use parent_id for simpler code
                    parent_id = grandparent.attrib.get("id")
        except:
            pass
    if parent_id and fact:
        node_element = anytree.Node(suffix,
                                    parent    = parent,
                                    parent_id = parent_id,
                                    #node_order= node_order,
                                    clark     = clark,
                                    prefix    = prefix,
                                    suffix    = suffix,
                                    fact      = fact,
                                    attrib    = attrib,
                                    )
    else:
        node_element = anytree.Node(suffix,
                                    parent    = parent,
                                    #node_order= node_order,
                                    clark     = clark,
                                    prefix    = prefix,
                                    suffix    = suffix,
                                    fact      = fact,
                                    attrib    = attrib,
                                    )
    elements.append(node_element)
    subtag_count_dict = {}
    for element in xbrl_element:
        count = subtag_count_dict.get(element.tag)
        if count is None:
            subtag_count_dict[element.tag] = 1
            count = 0
        else:
            subtag_count_dict[element.tag] = count + 1
        sub_elements = recursive_iter(element,
                                      reversed_ns,
                                      parent=node_element,
                                      node_order=count,
                                      )
        for element_sub2 in sub_elements:
            elements.append(element_sub2)
    return elements

def process_xbrl_file_to_tree(xbrl_filename):
    #print(xbrl_filename)
    tree, ns, root = extract_xbrl_tree_namespace_and_root(xbrl_filename)
    #print(root)
    reversed_ns = {value: key for key, value in ns.items()}
    elements = recursive_iter(root, reversed_ns)
    #print(len(elements))
    xbrl_tree_root = elements[0]
    return xbrl_tree_root

def convert_tree_to_dict(root_node):
    exporter = anytree.exporter.JsonExporter(indent=2, sort_keys=True)
    json_dict = json.loads(exporter.export(root_node))
    return json_dict

def convert_dict_to_node_tree(dict_to_convert):
    importer = anytree.importer.JsonImporter()
    json_str = json.dumps(dict_to_convert)
    root_node = importer.import_(json_str)
    return root_node

#### utils ####
def extract_xbrl_tree_namespace_and_root(xbrl_filename):
    ns = {}
    try:
        for event, (name, value) in ET.iterparse(xbrl_filename, ['start-ns']):
            if name:
                ns[name] = value
    except Exception as e:
        logging.error(e)
        return[None, None]
    tree = ET.parse(xbrl_filename)
    root = tree.getroot()
    return [tree, ns, root]

def xbrl_clark_prefix_and_suffix(xbrl_element, reversed_ns):
    clark, suffix = xbrl_element.tag[1:].split("}")
    prefix = reversed_ns.get(clark)
    return [clark, prefix, suffix]
def xbrl_ns_clark(xbrl_element):
    '''return clark notation prefix'''
    return xbrl_element.tag.split("}")[0][1:]
def xbrl_ns_prefix(xbrl_element, ns):

    return [key for key, value in ns.items() if xbrl_ns_clark(xbrl_element) == value][0]
def xbrl_ns_suffix(xbrl_element):

    return xbrl_element.tag.split("}")[1]
def return_xlink_locator(element_with_href):
    href = element_with_href.attrib.get("{http://www.w3.org/1999/xlink}href")
    href_list = href.split("#")
    if len(href_list) > 1:
        href = href_list[-1]
    return href

def import_json(xbrl_filename):
    with open('{}.json'.format(xbrl_filename), 'r') as inputfile:
        data_dict = json.load(inputfile)
    return data_dict
def write_dict_as_json(dict_to_write, xbrl_filename):
    with open('{}.json'.format(xbrl_filename), 'w') as outfile:
        json.dump(dict_to_write, outfile, indent=2)

#### xbrl from sec ####

def return_url_request_data(url, values_dict={}, secure=False, sleep=1):
    time.sleep(sleep)
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
    #logging.info(len(table_list))
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

def full_sec_xbrl_folder_download(cik, form_type, date="most recent"):
    response_data = sec_xbrl_single_stock(cik, form_type)
    logging.info("sec response_data gathered")
    relevant_xbrl_url = parse_sec_results_page(response_data, date=date)
    logging.info("precise url found")
    xbrl_data_page_response_data = return_url_request_data(relevant_xbrl_url)
    logging.info("xbrl data downloaded")
    folder_name = get_xbrl_files_and_return_folder_name(xbrl_data_page_response_data)
    logging.info("xbrl files created")
    return folder_name



if __name__ == "__main__":
    testing_appl = False
    if testing_appl:
        form_type = "10-K"
        ticker = 'aapl'
        cik = 320193
        folder_name, data_date = full_sec_xbrl_folder_download(cik, form_type)
        main_xbrl_to_json_converter(ticker, cik, folder_name)




#end of line