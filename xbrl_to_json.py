import sys, os, shutil, logging, datetime, json, time, copy, re, random
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
MONTH_IN_SECONDS = 60.0 * 60 * 24 * 7 * 30
PREFIXES_THAT_MATTER = ["us-gaap", "dei", "srt", "country"]

def main_xbrl_to_json_converter(ticker, cik, date, folder_path, delete_files_after_import=False):
    root_node_dict = {}
    potential_json_filename = return_xbrl_to_json_converted_filename_with_date(folder_path, ticker, date)
    # logging.info(potential_json_filename)
    ''' first we try to import the json files'''
    try:
        root_json = import_json(potential_json_filename)
        root_node = convert_dict_to_node_tree(root_json)
    except Exception as e:
        logging.error(e)
        root_node = None
    ''' if we don't have the root node, we need to get it from the actual files '''
    if not root_node:
        logging.info("json file does not already exist, creating one...")
        list_of_filenames_in_directory = os.listdir(folder_path)
        ''' we're going to iterate through the relevant xml/xsd files '''
        for filename in list_of_filenames_in_directory:
            if filename.endswith(".xml") or filename.endswith(".xsd"):
                xbrl_filename = os.path.join(folder_path, filename)
                logging.info("processing xbrl file: {}".format(xbrl_filename))
                ''' here we generate the root node '''
                root_node = xbrl_to_json_processor(xbrl_filename, ticker, write_file=testing_write_file, write_txt_file=testing_write_file)
                logging.info("done")
                root_node_dict[filename] = root_node
        ''' here we build up the whole tree '''
        fact_tree_root = fact_centric_xbrl_processor(root_node_dict, ticker)
        write_txt_file = not delete_files_after_import # if we're deleting files, lets not save a render.txt file
        ''' here get the root of the whole tree '''
        root_node = xbrl_to_json_processor(potential_json_filename, ticker, root_node=fact_tree_root, write_file=True, write_txt_file=write_txt_file)
        ''' this is an important ^^^ function '''

    if delete_files_after_import:
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            potential_txt_file = "{}.json_render.txt".format(folder_path)
            if os.path.isfile(potential_txt_file):
                os.remove(potential_txt_file)
    return root_node
def return_refernce_node(node, fact_tree_root, other_tree_root, ticker):
    ''' we create a refernce node for the underlying node if it doesn't exist,
        this will act as a parent node, since many nodes are related, but not directly.
        Note that this will be a "parent node" in the sense that...
        well, in the sense that it's a folder that contains related items
    '''
    local_prefixes_that_matter = PREFIXES_THAT_MATTER + [ticker.lower()]

    reference_node = None
    locator = None
    href = node.attrib.get("{http://www.w3.org/1999/xlink}href")
    if href:
        locator = return_xlink_locator(node)
    else:
        if node.clark not in clarks_to_ignore:
            locator = node.suffix
    if locator:
        ''' if a locator is present, this should be a fact item.
            here, with the prefixes_that_matter we're looking at locators that start with
            us-gaap_ or similar. This is, unfortunately, pretty common.
            It seems to creep in, and it'd be nice to avoid it in the refernces.
        '''
        locator_prefix = None
        modified_locator = None
        ''' check for the prefixes '''
        for prefix in local_prefixes_that_matter:
            if locator.startswith("{}_".format(prefix)):
                locator_prefix = prefix
                modified_locator = locator.replace("{}_".format(prefix), "")

        ''' next we look for a potential existing parent/reference node by name '''
        if modified_locator:
            reference_node = anytree.search.find_by_attr(fact_tree_root, modified_locator)
        else:
            reference_node = anytree.search.find_by_attr(fact_tree_root, locator)

        ''' if there is not a parent/reference node, we make one '''
        if not reference_node:
            ''' so all that follows is to try and mimic the structure of the base fact file with prefixes '''
            if modified_locator:
                if locator_prefix:
                    reference_node = anytree.Node(modified_locator,
                                         parent=fact_tree_root,
                                         prefix=locator_prefix,
                                         suffix=modified_locator)
                else:
                    reference_node = anytree.Node(modified_locator,
                                         parent=fact_tree_root,
                                         suffix=modified_locator)
            else:
                reference_node = anytree.Node(locator,
                                         parent=fact_tree_root,
                                         suffix=locator)
        ''' i'm going to try and associate the type of fact with the
            reference node
        '''
        try:
            ''' maybe a prefix already exists'''
            existing_prefix = reference_node.prefix
        except:
            ''' it doesn't so lets try and find one '''
            node_prefix=None
            ''' we want the node to have a fact
                (because we are looking for fact prefix from the main .xml file)
            '''
            try:
                node_fact = node.fact
            except:
                'probably not a fact node'
                node_fact = ""
            if node_fact != "":
                try:
                    node_prefix = node.prefix
                except:
                    node_prefix = None
            if node_prefix:
                reference_node.prefix = node_prefix


        return reference_node
    else:
        ''' this is a contextual item
            we will put this item in to the "other tree root" tree and deal with it later
        '''
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

    '''Here i'm going to attempt to order the files, to facilitate normal order:'''
    extension_order_after_primary_file_list = [".xsd", "_lab.xml",  "_def.xml",  "_cal.xml", "_pre.xml"]
    ordered_filename_list = []
    for extention in extension_order_after_primary_file_list:
        for filename in root_node_dict.keys():
            if filename.endswith(extention):
                ordered_filename_list.append(filename)
    '''now add the primary file:'''
    for filename in root_node_dict.keys():
        if filename not in ordered_filename_list:
            ordered_filename_list.insert(0, filename)

    '''here, we're just looking to see if a top level fact reference exists
        (could be made more efficient in the future, but limited)
    '''
    logging.info("Start initial sorting:")
    start_time = time.time()
    for filename in ordered_filename_list:
        logging.info(filename)
        ''' grab the root node '''
        root_node = root_node_dict.get(filename)
        ''' iterate through and look for suffixes, if one is missing, there's a major error '''
        for node in anytree.PreOrderIter(root_node):
            try:
                suffix = node.suffix
            except:
                logging.error("there is a problem with this node... it has no 'suffix' attribute")
                #pp.pprint(vars(node))
                sys.exit()

            ''' we create a refernce node if it doesn't exist,
                why: we're trying to prevent dublicates
                now let's pair it with that node
            '''
            reference_node = return_refernce_node(node, fact_tree_root, other_tree_root, ticker)
            parent_child_tuple_list.append((reference_node, node))

    ''' we iterate through, check for duplicates'''
    for reference_node, child in parent_child_tuple_list:
        ''' now lets unite all these nodes together '''
        unique = True
        ''' here we go through to check for duplicates '''
        for existing_child in reference_node.children:
            if vars(child) == vars(existing_child):
                '''this prevents lots of redundant nodes'''
                unique = False
            if unique == False:
                break
        if unique == True:
            ''' if we have a unique parent child relationship, we map it
                that is we attach the parent/reference node as the parent of our node
            '''
            child.parent = reference_node

        else:
            ''' here, our node is a duplicate, and so we throw it out '''
            child.parent = trash_tree_root
    ''' at this point we should have a basic tree structure with the base as the ticker'''
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))


    ''' now let's need to pair more of the other refernces with our facts'''
    logging.info("Start deep sorting:")
    start_time = time.time()
    ''' make a quick sort dict '''
    fact_tree_children_dict = {node.suffix: node for node in fact_tree_root.children}
    ''' got to the other other_tree_root and try to pair the stuff left over '''
    for node in anytree.PreOrderIter(other_tree_root):
        replacement_parent = return_new_parent(node, fact_tree_children_dict)
        if replacement_parent:
            node.parent = replacement_parent
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))



    #fact_tree_children_dict = {node.suffix: node for node in fact_tree_root.children}
    logging.info("Start deep sorting second pass:")
    start_time = time.time()
    for node in anytree.PreOrderIter(other_tree_root):
        replacement_parent = return_new_parent_round_two(node, fact_tree_children_dict)
        if replacement_parent:
            node.parent = replacement_parent
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))

    logging.info("Start contextRef sorting:")
    start_time = time.time()
    for node in anytree.PreOrderIter(fact_tree_root):
        replacement_parent = return_new_parent_for_Axis_contextRefs(node)
        if replacement_parent:
            node.parent = replacement_parent
    print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))

    logging.info("Create context refs dict:")
    start_time = time.time()
    convert_context_refs_into_id_keyed_dict(fact_tree_root, other_tree_root, trash_tree_root)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))


    if sort_trash_for_debugging:
        logging.info("Sort trash file:")
        start_time = time.time()
        trash_tree_root = keep_trash_sorted(trash_tree_root)
        logging.info("Finished in {}sec".format(round(time.time() - start_time)))


    logging.info("Saving text files")
    start_time = time.time()
    # the following are for testing:
    if testing:
        fact_tree_root_filename = ticker + "_facts"
        root_node_to_rendertree_text_file(fact_tree_root, fact_tree_root_filename)
        other_tree_root_filename = ticker + "_xbrli"
        root_node_to_rendertree_text_file(other_tree_root, other_tree_root_filename)
        trash_filename = ticker + "_trash"
        root_node_to_rendertree_text_file(trash_tree_root, trash_filename)
    logging.info("Finished in {}sec".format(round(time.time() - start_time)))

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
                    logging.error("This should not happen. Examine this code error")
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
    logging.info("old trash tree")
    logging.info(anytree.RenderTree(trash_tree_root))
    return sorted_trash_tree_root
def print_root_node_lengths(fact_tree_root, other_tree_root, trash_tree_root):
    fact_tree_root_len = len(list(anytree.PreOrderIter(fact_tree_root)))
    other_tree_root_len = len(list(anytree.PreOrderIter(other_tree_root)))
    trash_tree_root_len = len(list(anytree.PreOrderIter(trash_tree_root)))
    logging.info("facts:\t{}\tother:\t{}\ttrash:\t{}".format(fact_tree_root_len, other_tree_root_len, trash_tree_root_len))
def return_new_parent(node, fact_tree_children_dict):
    # step 1: recursion
    try:
        parent_id = node.parent_id
    except:
        parent_id = None
    if parent_id:
        parent = fact_tree_children_dict.get(parent_id)
        if parent:
            return parent
    # step 2: start check dimension
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
    # step 3 check label
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
    # step 5: from and to attributes
    try:
        from_attrib = node.attrib.get("{http://www.w3.org/1999/xlink}from")
        to_attrib = node.attrib.get("{http://www.w3.org/1999/xlink}to")
    except:
        from_attrib = None
        to_attrib = None
    if from_attrib and to_attrib:
        ''' i decided not to make copies, but instead, just leave them in the from attributes'''
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
    # step 4 roles
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
def return_new_parent_for_Axis_contextRefs(node):
    try:
        contextRef = node.attrib.get('contextRef')
    except:
        return
    if contextRef is None:
        return
    split_contextRef = contextRef.split("_")
    if len(split_contextRef) == 1:
        return
    if "Axis" in contextRef:
        for index, sub_string in enumerate(split_contextRef):
            if sub_string.endswith("Axis"):
                parent = node.parent

                for child in parent.children:
                    if child.suffix == sub_string:
                        return child
                # we should have establish there is no pre-existing subparent if we are here
                subparent = anytree.Node(sub_string,
                                    parent              = parent,
                                    # node_order        = node_order,
                                    suffix              = sub_string,
                                    axis                = True
                                    )
                return subparent
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
def xbrl_to_json_processor(xbrl_filename, ticker, root_node=None, write_file=False, write_txt_file=False):
    if not (xbrl_filename or root_node):
        logging.error("You must include a either a filename or root_node")
        sys.exit()
    if not root_node:
        root_node = process_xbrl_file_to_tree(xbrl_filename, ticker)
    #print(anytree.RenderTree(root_node))
    flat_file_dict = convert_tree_to_dict(root_node)
    if write_file:
        should_be_json_filename = xbrl_filename
        if not should_be_json_filename.endswith(".json"):
            should_be_json_filename = should_be_json_filename + ".json"
        write_dict_as_json(flat_file_dict, should_be_json_filename)
        if write_txt_file:
            root_node_to_rendertree_text_file(root_node, should_be_json_filename)
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
def root_node_to_rendertree_text_file(root_node, xbrl_filename, custom=False):
    with open('{}_render.txt'.format(xbrl_filename), 'w') as outfile:
            if custom:
                output_str = custom_render_tree(root_node)
            else:
                output_str = str(anytree.RenderTree(root_node))
            outfile.write(output_str)
def recursive_iter(xbrl_element, reversed_ns, ticker, parent=None, node_order=0):
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
                                      ticker,
                                      parent=node_element,
                                      node_order=count,
                                      )
        for element_sub2 in sub_elements:
            elements.append(element_sub2)
    return elements
def process_xbrl_file_to_tree(xbrl_filename, ticker):
    logging.info(xbrl_filename)
    tree, ns, root = extract_xbrl_tree_namespace_and_root(xbrl_filename)
    #print(root)
    reversed_ns = {value: key for key, value in ns.items()}
    elements = recursive_iter(root, reversed_ns, ticker)
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
        return[None, None, None]
    tree = ET.parse(xbrl_filename)
    root = tree.getroot()
    #logging.info([tree, ns, root])
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
def import_json(json_filename):
    logging.info("importing: {}".format(json_filename))
    with open(json_filename, 'r') as inputfile:
        data_dict = json.load(inputfile)
    return data_dict
def write_dict_as_json(dict_to_write, json_filename):
    logging.info("writing: {}".format(json_filename))
    with open(json_filename, 'w') as outfile:
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
def parse_sec_results_page(sec_response_data, date="most recent", previous_error=False):
    soup = bs4.BeautifulSoup(sec_response_data, 'html.parser')
    table_list = soup.find_all("table", {"summary": "Results"})
    #logging.info(len(table_list))
    if not len(table_list) == 1:
        logging.error("something's up here")
    table = table_list[0]
    document_button_list = table.find_all("a", {"id":"documentsbutton"})
    if not date:
        date = "most recent"
    if date == "most recent":
        relevant_a_tag = table.find("a", {"id":"documentsbutton"})
        if previous_error:
            relevant_interactive_tag = table.find("a", {"id":"interactiveDataBtn"})
            tag_parent = relevant_interactive_tag.parent
            relevant_a_tag = tag_parent.find("a", {"id":"documentsbutton"})
    else:
        year = date[:4]
        month = date[4:6]
        day = date[6:]
        logging.info("{}-{}-{}".format(year, month, day))
        relevant_td = table.find("td", string="{}-{}-{}".format(year, month, day))
        relevant_td_parent = None
        if not relevant_td:
            relevant_interactive_tags = table.find_all("a", {"id":"interactiveDataBtn"})
            tag_parents = [tag.parent.parent for tag in relevant_interactive_tags]
            if tag_parents:
                # i'm going to get clever here, and count backwards through the months
                # starting with the listed month, to find the nearest previous entry
                # if the month is correct, it should work the first time
                # if you encounter an error here, that's what's happening
                for i in reversed(range(int(month))):
                    month_str = str(i+1).zfill(2)
                    date_str = "{}-{}".format(year, month_str)
                    for parent in tag_parents:
                        if date_str in parent.text:
                            for child in parent.children:
                                if child.string:
                                    if date_str in child.string:
                                        relevant_td = child
                                        if relevant_td:
                                            break
                        if relevant_td:
                            break
                    if relevant_td:
                        break
        relevant_td_parent = relevant_td.parent
        relevant_a_tag = relevant_td_parent.find("a", {"id":"documentsbutton"})
    relevant_a_href = relevant_a_tag['href']
    sec_url = "https://www.sec.gov"
    relevant_xbrl_url = sec_url + relevant_a_href
    return relevant_xbrl_url
def write_xbrl_file(file_name, sec_response_data):
    with open(file_name, 'w') as outfile:
        outfile.write(sec_response_data)
def return_xbrl_data_formatted_folder_path(ticker, form_type):

    return os.path.join("XBRL_Data", ticker, form_type)
def return_most_recent_xbrl_to_json_converted_filename(folder_path, ticker):
    filename = find_most_recent_filename_from_date(folder_path, ticker)
    return os.path.join(folder_path, filename)
def return_xbrl_to_json_converted_filename_with_date(folder_path, ticker, date):
    ticker_date = "{}-{}".format(ticker, date)
    if folder_path.endswith(ticker_date):
        filename = folder_path + ".json"
    else:
        filename = ticker_date + ".json"
        filename = os.path.join(folder_path, filename)
    return filename
def find_most_recent_filename_from_date(folder_path, ticker):
    pattern = re.compile(ticker.lower() + r"-[0-9]{8}")
    most_recent_folder_date = 0
    most_recent_filename = None
    for filename in os.listdir(folder_path):
        #logging.info(filename)
        if filename.endswith(".json"):
            if ticker.lower() in filename:
                if pattern.search(filename):
                    ticker_hyphen_date = filename.replace(".json", "")
                    folder_date = ticker_hyphen_date.split("-")[1]
                    if int(folder_date) > most_recent_folder_date:
                        most_recent_folder_date = int(folder_date)
                        most_recent_filename = filename
    return most_recent_filename
def get_xbrl_files_and_return_folder_name(ticker, xbrl_data_page_response_data, form_type, url_in_case_of_error=None):
    soup = bs4.BeautifulSoup(xbrl_data_page_response_data, 'html.parser')
    table_list = soup.find_all("table", {"summary": "Data Files"})
    if not len(table_list) == 1:
        logging.error("something's up here")
        #pp.pprint(table_list)
        if not table_list:
            logging.error("Likely refering to a sec page without XBRL, manually check the url")
            logging.error(url_in_case_of_error)
            return "Error: No Table"
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
        full_file_name = os.path.join("XBRL_Data", ticker, form_type, folder_name, file_name)
        full_folders_name = os.path.join("XBRL_Data", ticker, form_type, folder_name)
        if not os.path.exists(full_folders_name):
            os.makedirs(full_folders_name)
        else:
            if os.path.exists(full_file_name):
                logging.info("Data for {} already exists".format(ticker))
                return full_folders_name, data_date
        full_url = sec_url + href
        response_data = return_url_request_data(full_url)
        write_xbrl_file(full_file_name, response_data)
    return full_folders_name, data_date
def full_sec_xbrl_folder_download(ticker, cik, form_type, date="most recent", previous_error=False):
    response_data = sec_xbrl_single_stock(cik, form_type)
    logging.info("sec response_data gathered")
    relevant_xbrl_url = parse_sec_results_page(response_data, date=date, previous_error=previous_error)
    logging.info("precise url found")
    xbrl_data_page_response_data = return_url_request_data(relevant_xbrl_url)
    logging.info("xbrl data downloaded")
    folder_name = get_xbrl_files_and_return_folder_name(ticker, xbrl_data_page_response_data, form_type, url_in_case_of_error=relevant_xbrl_url)
    if folder_name == "Error: No Table":
        if not previous_error:
            return full_sec_xbrl_folder_download(ticker, cik, form_type, date=date, previous_error=True)
        else:
            logging.error("error loop here")
            return
    logging.info("xbrl files created")
    return folder_name
def main_download_and_convert(ticker, cik, form_type, year=None, month=None, day=None, force_download=False, delete_files_after_import=False):
    given_date = None
    if year and (month and day):
        try:
            year = str(year).zfill(4)
            month = str(month).zfill(2)
            day = str(day).zfill(2)
            given_date = "{}{}{}".format(year, month, day)
        except:
            logging.error("invalid year/month/date input")
    # start by converting to path name
    path = return_xbrl_data_formatted_folder_path(ticker, form_type)
    logging.info(path)
    if not os.path.exists(path):
        os.makedirs(path)
    # if we are going to force a download attempt, the following can all be skipped
    if not force_download:
        # if we have a specific date we're looking for, this will do that
        if given_date:
            try:
                folder_name = "{}-{}".format(ticker.lower(), given_date)
                path = os.path.join(path, folder_name)
                if os.path.exists(path):
                    xbrl_tree_root = main_xbrl_to_json_converter(ticker, cik, given_date, path, delete_files_after_import=delete_files_after_import)
                    return xbrl_tree_root
            except Exception as e:
                logging.warning(e)
                logging.info("probably no date given")
                pass
        # if we have no date enterend (the standard case) and there *are* files
        # then we will check the last month
        # if there are no files from the last month, we will attempt to download from the SEC
        else:
            pattern = re.compile(ticker.lower() + r"-[0-9]{8}")
            most_recent_folder_date = 0
            folder_ymd_tuple = None
            for filename in os.listdir(path):
                #logging.info(filename)
                #logging.info(pattern.search(filename))
                if filename.endswith(".json") and "facts_dict" not in filename:
                    if ticker.lower() in filename:
                        if pattern.search(filename):
                            ticker_hyphen_date = filename.replace(".json", "")
                            folder_date = ticker_hyphen_date.split("-")[1]
                            #logging.info("{} {}".format(folder_date, most_recent_folder_date))
                            if int(folder_date) > most_recent_folder_date:
                                most_recent_folder_date = int(folder_date)
                                folder_ymd_tuple = (ticker_hyphen_date, str(most_recent_folder_date)[:4], str(most_recent_folder_date)[4:6], str(most_recent_folder_date)[6:])
            if folder_ymd_tuple:
                #logging.info("one line below")
                #pp.pprint(folder_ymd_tuple)
                most_recent_folder_time = time.strptime("{}:{}:{}".format(folder_ymd_tuple[1], folder_ymd_tuple[2], folder_ymd_tuple[3]), "%Y:%m:%d")
                most_recent_folder_time = time.mktime(most_recent_folder_time)
                now = float(time.time())
                period_seconds = 0
                if form_type == "10-K":
                    period_seconds = MONTH_IN_SECONDS * 12
                elif form_type == "10-Q":
                    period_seconds = MONTH_IN_SECONDS * 3
                if now < (most_recent_folder_time + period_seconds): # if the folder is less than expected period for the next form
                    path = os.path.join(path, folder_ymd_tuple[0])
                    xbrl_tree_root = main_xbrl_to_json_converter(ticker, cik, most_recent_folder_date, path, delete_files_after_import=delete_files_after_import)
                    return xbrl_tree_root
    folder_name, data_date = full_sec_xbrl_folder_download(ticker, cik, form_type, date=given_date)
    xbrl_tree_root = main_xbrl_to_json_converter(ticker, cik, data_date, folder_name, delete_files_after_import=delete_files_after_import)
    convert_root_node_facts_to_fact_dict(xbrl_tree_root, ticker, folder_name)
    return xbrl_tree_root
#### extract xbrl data from tree ####
def recursive_get_fact_and_entry_dict_from_axis_member_dict(node_dict, axis_member_list, date):
    axis_member_iter_list = axis_member_list[1:]
    print(axis_member_iter_list)
    entry_dict = node_dict
    pp.pprint(node_dict)
    for index, item in enumerate(axis_member_iter_list):
        entry_dict = entry_dict.get(item)
    fact = entry_dict.get(date)
    return fact, entry_dict
def recursive_set_axis_member_dict(node_dict, axis, member, axis_member_list, date):
    if node_dict is None:
        print(axis)
        print(member)
        print(axis_member_list)
    axis_entry = node_dict.get(axis)
    if axis_entry is None:
        node_dict[axis] = {member: {}}
    member_entry = node_dict[axis].get(member)
    if member_entry is None:
        node_dict[axis][member] = {}
    index = axis_member_list.index(member)
    if index < len(axis_member_list)-1: # we aren't done with recursion
        new_dict = node_dict[axis].get(member)
        print("\n")
        pp.pprint(node_dict)
        print(axis_member_list)
        print("\n")
        node_dict[axis][member] = recursive_set_axis_member_dict(
                                        new_dict,
                                        axis_member_list[index + 1],
                                        axis_member_list[index + 2],
                                        axis_member_list,
                                        date)
    else:
        member_entry = node_dict[axis].get(member)
        if not member_entry:
            node_dict[axis][member] = {date: None}
        else:
            fact = node_dict[axis][member].get(date)
            if fact is None:
                node_dict[axis][member] = {date: None}
            else:
                print("fact!")
    print("\n")
    print(node_dict)
    return node_dict
def convert_root_node_facts_to_fact_dict(root_node, ticker, folder_name):
    local_prefixes_that_matter = PREFIXES_THAT_MATTER + [ticker.lower()]
    print(local_prefixes_that_matter)
    dict_to_return = {}
    item_depth = 1
    context_dict = anytree.findall_by_attr(root_node, "context_dict", maxlevel=2)[0].attrib
    # print(context_dict)
    for node in anytree.PreOrderIter(root_node):
        if node.depth == item_depth:
            try:
                suffix = node.suffix
                dict_to_return[suffix] = {}
            except:
                print("failed at suffix")
                continue
        try:
            fact = node.fact
        except:
            continue
        if fact == '':
            #print("no fact")
            continue
        try:
            context_ref = node.attrib.get("contextRef")
        except Exception as e:
            print("failed at context_ref")
            continue
        if context_ref is None:
            #print("failed at context_ref is None")
            continue
        date = context_dict.get(context_ref)
        if not date:
            print("failed at date")
            continue

        # check for axis numbers
        try:
            axis = node.parent.axis
        except:
            axis = False

        node_dict = dict_to_return.get(node.suffix)
        if not node_dict:
            node_dict = {}
        if not axis:
            previous_entry = dict_to_return[node.suffix].get(date)
            entry_dict = dict_to_return.get(node.suffix)
        else: # we need a complicated axis-member relationship (similar date, but subcatigory)
            context_split = context_ref
            for prefix in local_prefixes_that_matter:
                context_split = context_split.replace(prefix, "")
            context_split = context_split.split("_")
            context_split = [x for x in context_split if x != '']
            recursive_set_axis_member_dict(node_dict,
                                           context_split[1],
                                           context_split[2],
                                           context_split,
                                           date)
            previous_entry, entry_dict = recursive_get_fact_and_entry_dict_from_axis_member_dict(
                                           node_dict,
                                           context_split,
                                           date)
        if previous_entry is not None:
            if previous_entry != fact:
                print("date: {}".format(date))
                print("previous entry: {}".format(previous_entry))
                print("current fact: {}".format(fact))
                print("failed at previous_entry != node.fact")
                continue
            else:
                raise(Exception("Previous Entry for: {}|{}|{}".format(node.suffix, date, node.fact)))
        else:
            entry_dict[date] = fact


    dict_to_return = {ticker: dict_to_return}
    json_filename = "{}_facts_dict.json".format(folder_name)
    write_dict_as_json(dict_to_return, json_filename)
def get_data_node(root_node, attribute_name, date=None, subcategory=None):
    if date is not None:
        context_dict = anytree.findall_by_attr(root_node, "context_dict", maxlevel=2)[0].attrib
    node_tuple = anytree.findall_by_attr(root_node, attribute_name, maxlevel=2)

    if node_tuple:
        if len(node_tuple) != 1:
            logging.error("There are multiple attribute nodes with the same name. This should not happen.")
            return
        node = node_tuple[0]
        if date is None:
            return node
        # else let's find the date
        context_ref = None
        context_ref_list = [key for key, value in context_dict.items() if value == date]
        if len(context_ref_list) == 1:
            return context_ref_list[0]
        if not subcategory:
            context_ref_list = [ref for ref in context_ref_list if not '_' in ref]
            if len(context_ref_list) > 1:
                logging.error("More than one base category date")
                #pp.pprint(context_ref_list)
                sys.exit()
            context_ref = context_ref_list[0]
        else:
            subcategory_list = []
            for ref in context_ref_list:
                ref_split_list = ref.split("_", maxsplit=1)
                if ref_split_list:
                    if subcategory == ref_split_list[-1]:
                        subcategory_list.append(ref)
            if not subcategory_list:
                return
            if len(subcategory_list) > 1:
                logging.error("More than one subcategory date")
                #pp.pprint(context_ref_list)
                sys.exit()
            context_ref = subcategory_list[0]
        if context_ref:
            for subnode in anytree.PreOrderIter(node):
                try:
                    subnode_context_ref = subnode.attrib.get("contextRef")
                except:
                    continue
                if subnode_context_ref:
                    if context_ref == subnode_context_ref:
                        return subnode
    else:
        logging.error("No attributes of that name")
def convert_to_datetime(string_date_YYYY_MM_DD):
    string_date_list = string_date_YYYY_MM_DD.split(":")
    #logging.info(string_date_list)
    if len(string_date_list) == 2:
        start_date = string_date_list[0]
        end_date = string_date_list[1]
    elif len(string_date_list) == 1:
        end_date = string_date_list[0]
        start_date = None
    else:
        logging.error("{} is not a valid date string".format(string_date_YYYY_MM_DD))
    end_datetime_object = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    if start_date:
        start_datetime_object = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start_datetime_object = None
    time_delta = None
    if end_datetime_object and start_datetime_object:
        time_delta = end_datetime_object - start_datetime_object
    return [end_datetime_object, start_datetime_object, time_delta]
def y_or_q_and_form_type_from_limit_data(Y_or_Q, form_type):
    if form_type and not Y_or_Q:
        if form_type == "10-K":
            Y_or_Q = "Y"
        elif form_type == "10-Q":
            Y_or_Q = "Q"
    elif Y_or_Q and not form_type:
        if Y_or_Q == "Y":
            form_type = "10-K"
        elif Y_or_Q == "Q":
            form_type = "10-Q"
    elif not (form_type or Y_or_Q):
        Y_or_Q = "Y"
        form_type = "10-K"
    return Y_or_Q, form_type
def get_most_recent_data(root_node, attribute_name, Y_or_Q=None, form_type=None, subcategory=None):
    return get_most_recent_multiple_instances(root_node, attribute_name, 1, Y_or_Q=Y_or_Q, form_type=form_type, subcategory=subcategory)[0]
    # if not Y_or_Q:
    #     Y_or_Q, form_type = y_or_q_and_form_type_from_limit_data(Y_or_Q, form_type)

    # context_dict = anytree.findall_by_attr(root_node, "context_dict", maxlevel=2)[0].attrib

    # relevant_node = anytree.findall_by_attr(root_node, attribute_name, maxlevel=2)
    # if not relevant_node:
    #     logging.warning("no relevant node")
    #     return

    # if len(relevant_node) != 1:
    #     logging.error("There are multiple attribute nodes with the same name. This should not happen.")
    #     return

    # relevant_node = relevant_node[0]

    # node_contextRef_date_tuple_list = []

    # for node in anytree.PreOrderIter(relevant_node):
    #     #logging.info(node)
    #     basic_contextRef = None
    #     if subcategory:
    #         contextRef = return_context_ref(node)
    #         if contextRef:
    #             if subcategory in contextRef:
    #                 basic_contextRef = return_basic_context_ref(node)
    #     elif is_basic_date_context_ref(node):
    #         #logging.info('is basic_contextRef')
    #         basic_contextRef = return_context_ref(node)
    #         #print(basic_contextRef)
    #     if basic_contextRef:
    #         the_context = context_dict.get(basic_contextRef)
    #         #logging.info(the_context)
    #         node_contextRef_date_tuple_list.append([node, basic_contextRef, the_context])

    # if not node_contextRef_date_tuple_list:
    #     logging.warning("no nodes matched")

    # narrowed_list = []
    # if Y_or_Q == 'Y':
    #     applicable_refs = ["YTD"]
    # if Y_or_Q == 'Q':
    #     applicable_refs = ["Q4", "Q3", "Q2", "Q1", "QTD"]
    # for node_contextRef_date_tuple in node_contextRef_date_tuple_list:
    #     for ref in applicable_refs:
    #         if node_contextRef_date_tuple[1].endswith(ref):
    #             narrowed_list.append(node_contextRef_date_tuple)
    # node_contextRef_date_tuple_list = narrowed_list

    # most_recent_time = datetime.datetime.strptime("0001-01-01", "%Y-%m-%d")
    # most_recent_list = []
    # for node_contextRef_date_tuple in node_contextRef_date_tuple_list:
    #     context_date = node_contextRef_date_tuple[2]
    #     end_datetime, start_date, time_delta = convert_to_datetime(context_date)
    #     if end_datetime > most_recent_time:
    #         most_recent_time = end_datetime
    #         most_recent_list = [node_contextRef_date_tuple]
    #     elif end_datetime == most_recent_time:
    #         most_recent_list.append(node_contextRef_date_tuple)

    # if not most_recent_list:
    #     logging.warning("There are no facts that match that search")
    #     return
    # elif len(most_recent_list) == 1:
    #     #logging.info([[x[1], x[2]] for x in most_recent_list])
    #     return most_recent_list[0][0]
    # else:
    #     #logging.warning("There are more than one most recent, checking for duplicates")
    #     ''' remove potential dublicates'''
    #     fact_context_tuple_list = []
    #     unique_data_list = []
    #     for node_contextRef_date_tuple in most_recent_list:
    #         data_node = node_contextRef_date_tuple[0]
    #         contextRef = node_contextRef_date_tuple[1]
    #         date = node_contextRef_date_tuple[2]
    #         try:
    #             fact = data_node.fact
    #         except:
    #             fact = None
    #         #logging.info("{} {} {}".format(fact, contextRef, date))
    #         data_tuple = (data_node.fact, contextRef, date)
    #         if not data_tuple in fact_context_tuple_list:
    #             fact_context_tuple_list.append(data_tuple)
    #             unique_data_list.append(data_node)
    #     #logging.info(unique_data_list)
    #     if len(unique_data_list) == 1:
    #         return unique_data_list[0]
    #     else:
    #         logging.warning("there are still more than one most recent piece of data")
    #         # checking_y_or_q_list = []
    #         # if Y_or_Q:
    #         #     for data_node in unique_data_list:
    #         #         data_tuple = (data_node.fact, data_node.attrib.get("contextRef"))
    #         #         if data_tuple[1].endswith("{}TD".format(Y_or_Q)) in fact_context_tuple_list:
    #         #             checking_y_or_q_list.append(data_node)
    #         # if len(checking_y_or_q_list) > 1:
    #         #    logging.warning("god damn it, there are still more than one most recent piece of data")
    #         #    return checking_y_or_q_list
    #         return checking_y_or_q_list[0]
def get_most_recent_multiple_instances(root_node, attribute_name, number_of_instances, Y_or_Q=None, form_type=None, subcategory=None):
    if not Y_or_Q:
        Y_or_Q, form_type = y_or_q_and_form_type_from_limit_data(Y_or_Q, form_type)

    context_dict = anytree.findall_by_attr(root_node, "context_dict", maxlevel=2)[0].attrib

    relevant_node = anytree.findall_by_attr(root_node, attribute_name, maxlevel=2)
    if not relevant_node:
        logging.warning("no relevant node")
        return

    if len(relevant_node) != 1:
        logging.error("There are multiple attribute nodes with the same name. This should not happen.")
        return

    relevant_node = relevant_node[0]

    node_contextRef_date_tuple_list = []

    for node in anytree.PreOrderIter(relevant_node):
        #logging.info(node)
        basic_contextRef = None
        if subcategory:
            contextRef = return_context_ref(node)
            if contextRef:
                if subcategory in contextRef:
                    basic_contextRef = return_basic_context_ref(node)
        elif is_basic_date_context_ref(node):
            #logging.info('is basic_contextRef')
            basic_contextRef = return_context_ref(node)
            #print(basic_contextRef)
        if basic_contextRef:
            the_context = context_dict.get(basic_contextRef)
            #logging.info(the_context)
            node_contextRef_date_tuple_list.append([node, basic_contextRef, the_context])

    if not node_contextRef_date_tuple_list:
        logging.warning("no nodes matched")

    narrowed_list = []
    logging.info("Y_or_Q == {}".format(Y_or_Q))
    if Y_or_Q == 'Y':
        applicable_refs = ["YTD"]
    if Y_or_Q == 'Q':
        applicable_refs = ["Q4", "Q3", "Q2", "Q1", "QTD"]
    for node_contextRef_date_tuple in node_contextRef_date_tuple_list:
        for ref in applicable_refs:
            if node_contextRef_date_tuple[1].endswith(ref):
                narrowed_list.append(node_contextRef_date_tuple)
    node_contextRef_date_tuple_list = narrowed_list

    most_recent_list = []
    for node_contextRef_date_tuple in node_contextRef_date_tuple_list:
        context_date = node_contextRef_date_tuple[2]
        end_datetime, start_date, time_delta = convert_to_datetime(context_date)
        if not most_recent_list:
            most_recent_list.append(node_contextRef_date_tuple)
        for index, existing_node_contextRef_date_tuple_list in enumerate(most_recent_list):
            newer_than_index = None
            existing_context_date = existing_node_contextRef_date_tuple_list[2]
            existing_end_datetime, existing_start_date, existing_time_delta = convert_to_datetime(existing_context_date)
            if end_datetime > existing_end_datetime:
                newer_than_index = index
            elif end_datetime == existing_end_datetime:
                try:
                    node_fact = node_contextRef_date_tuple_list[0].fact
                except:
                    node_fact = None
                try:
                    existing_fact = existing_node_contextRef_date_tuple_list[0].fact
                except:
                    existing_fact = None
                if node_fact == existing_fact:
                    if start_date == existing_start_date:
                        logging.warning("duplicate fact, skipping")
                        continue
                    else:
                        if time_delta is not None:
                            if Y_or_Q == "Y":
                                if time_delta.days() < 300:
                                    logging.warning("quarterly term for annual request, skipping")
                                    continue
                            elif Y_or_Q == "Q":
                                if time_delta.days() > 50:
                                    logging.warning("annual term for quarterly request, skipping")
                                    continue
                    logging.warning("odd, but near identical facts are being grouped together")
                    newer_than_index = index
            if newer_than_index:
                most_recent_list.insert(newer_than_index, node_contextRef_date_tuple)

    if most_recent_list:
        most_recent_list = [node_ref_date_triple[0] for node_ref_date_triple in most_recent_list]

    if not most_recent_list:
        logging.warning("There are no facts that match that search")
        return
    elif len(most_recent_list) < number_of_instances:
        #logging.info([[x[1], x[2]] for x in most_recent_list])
        return most_recent_list
    else:
        return most_recent_list[0:number_of_instances]
def print_all_simple_context_refs(root_node):
    pattern = re.compile(r'[A-Z]{1,2}[0-9]{4}[A-Z]{1}[0-9]{1}(YTD|QTD)?(?=\s)')
    simple_context_set = set()
    context_ref_list = []
    for node in anytree.PreOrderIter(root_node):
        context_ref = None
        try:
            context_ref = node.attrib.get("contextRef")
            if context_ref is not None:
                context_ref_list.append(context_ref)
        except:
            continue
        if context_ref is not None:
            for ref in context_ref_list:
                ref_split_list = ref.split("_", maxsplit=1)
                if len(ref_split_list) == 1:
                    simple_context_set.add(ref)
    big_string = ""
    for ref in simple_context_set:
        big_string = "{}{}\n".format(big_string, ref)
    logging.info(big_string)
    logging.info(type(big_string))

    matches = pattern.finditer(big_string)
    logging.info(len(simple_context_set))
    match_list = [match for match in matches]
    logging.info(len(match_list))
    #pp.pprint(match_list)
    span_list = [match.span() for match in match_list]
    str_list = [big_string[span[0]: span[1]] for span in span_list]
    #pp.pprint(str_list)
    #pp.pprint([x for x in simple_context_set if x not in str_list])
def non_basic_context_ref_pattern(root_node, attribute_name = None):
    if not attribute_name:
        # print full contextref bases
        context_dict = anytree.findall_by_attr(root_node, "context_dict", maxlevel=2)[0].attrib
        context_ref_list = context_dict.keys()
        ref_list = []
        for ref in sorted(context_ref_list):
            if len(ref.split("_")) > 1:
                pass
                #ref_list.append(ref.split("_")[0])
            else:
                #pass
                ref_list.append(ref)
        ref_list = list(set(ref_list))
        logging.info("")
        for ref in sorted(ref_list):
            logging.info(ref)
    if attribute_name:
        attribute_node = anytree.findall_by_attr(root_node, attribute_name, maxlevel=2)
        if not attribute_node:
            return
        attribute_node = attribute_node[0]
        attribute_ref_list = []
        for node in anytree.PreOrderIter(attribute_node):
            try:
                attribute_ref_list.append(node.attrib.get("contextRef"))
            except:
                pass
        attribute_ref_list = sorted(list(set([ref.split("_")[0] for ref in attribute_ref_list if ref is not None])))
        for ref in attribute_ref_list:
            logging.info(ref)
def get_most_recent_annual_data(root_node, attribute_name, date=None, subcategory=None):

    return get_most_recent_data(root_node, attribute_name, Y_or_Q="Y")
def get_most_recent_quarterly_data(root_node, attribute_name, date=None, subcategory=None):

    return get_most_recent_data(root_node, attribute_name, Y_or_Q="Q")
def get_top_data_node(root_node, attribute_name):
    relevant_node = anytree.findall_by_attr(root_node, attribute_name, maxlevel=2)
    return relevant_node
def return_context_ref(node):
    try:
        return node.attrib.get('contextRef')
    except:
        return
def return_basic_context_ref(node):
    full_contextRef = return_context_ref(node)
    split_contextRef = return_split_context_ref_list(full_contextRef)
    if split_contextRef:
        basic_contextRef = split_contextRef[0]
        return basic_contextRef
def return_split_context_ref_list(contextRef):
    if contextRef is None:
        return
    return contextRef.split("_")
def is_basic_date_context_ref(node):
    contextRef = return_context_ref(node)
    if contextRef:
        if len(contextRef.split("_")) == 1:
            return True
def analayse_split_context_ref(node):
    contextRef = return_context_ref(node)
    split_contextRef = return_split_context_ref_list(contextRef)
    if split_contextRef is None:
        return

    # the vast majority of the time this will happen
    dict_to_return = {"base": split_contextRef[0]}
    if len(split_contextRef) == 1:
        return dict_to_return

    #else
    if "Axis" in contextRef:
        dict_to_return.update(return_axis_based_context_ref_dict(split_contextRef))
    #pp.pprint(dict_to_return)
    return dict_to_return
def return_axis_based_context_ref_dict(split_contextRef):
    dict_to_return = {}
    list_len = len(split_contextRef)
    indices_of_axis_strs = []
    double_check_list = [split_contextRef[0]]
    for index, sub_string in enumerate(split_contextRef):
        if sub_string.endswith("Axis"):
            indices_of_axis_strs.append(index)
    for index, axis_index in enumerate(indices_of_axis_strs):
        index_str = ""
        if index > 0:
            index_str = "_{}".format(index+1)
        axis_string = split_contextRef[axis_index]
        dict_to_return.update({"axis_string{}".format(index_str): axis_string})
        prefix = None
        if axis_index > 0:
            prefix = split_contextRef[axis_index - 1]
            dict_to_return.update({"axis_prefix{}".format(index_str): prefix})
            double_check_list.append(prefix)
        double_check_list.append(axis_string)

        subcategory_prefix = None
        axis_subcategory = None
        try:
            subcategory_prefix = split_contextRef[axis_index + 1]
            axis_subcategory = split_contextRef[axis_index + 2]
        except:
            pass
        if subcategory_prefix and axis_subcategory:
            dict_to_return.update({
                "axis_subcategory_prefix{}".format(index_str): subcategory_prefix,
                "axis_subcategory{}".format(index_str): axis_subcategory,
                })
            double_check_list.append(subcategory_prefix)
            double_check_list.append(axis_subcategory)
    if not double_check_list == split_contextRef:
        axis_extra = [x for x in split_contextRef if x not in double_check_list]
        dict_to_return.update({"axis_extra": axis_extra})
    return dict_to_return

delete_after_import = False
testing_write_file = False
force_download = False
testing = False
if __name__ == "__main__":
    testing = False
    if testing:
        randomize = False
        date_specific = False
        delete_after_import = False
        testing_write_file = True
        force_download = False
        stock_ticker = 'aapl'
        form = '10-K'

        appl = ('aapl', 320193, 2018, 9, 29)
        ge = ('ge', 40545, 2018, 12, 31)
        chuy = ('chuy', 1524931, 2018, 12, 30)
        stocks = [appl, ge, chuy]
        forms = ["10-K", "10-Q"]
        form_choice  = forms.index(form)
        if randomize:
            random_form = random.choice(forms)
            logging.info(random_form)
            form_choice = forms.index(random_form)
        form_type = forms[form_choice]

        # stock_list = []
        # for stock in []:stocks:
        #     logging.info("{} {} {}".format(stock[0], stock[1], form_type))
        #     if date_specific:
        #         xbrl_tree_root = main_download_and_convert(stock[0], stock[1], form_type, year=stock[2], month=stock[3], day=stock[4])
        #     else:
        #         xbrl_tree_root = main_download_and_convert(stock[0], stock[1], form_type, delete_files_after_import=delete_after_import, force_download=force_download)
        #     stock_list.append(xbrl_tree_root)

        # stock_choice = [stock for stock in stock_list if stock.name.lower() == stock_ticker.lower()][0]
        # if randomize:
        #     stock_choice = random.choice(stock_list)

        stock = stocks[0]
        xbrl_tree_root = main_download_and_convert(stock[0], stock[1], form_type, delete_files_after_import=delete_after_import, force_download=force_download)
        #logging.info(get_most_recent_data(apple_root, "LongTermDebtNoncurrent", "Q"))

        #print("EntityCommonStockSharesOutstanding")
        #get_most_recent_data(xbrl_tree_root, "EntityCommonStockSharesOutstanding", y_or_q_choice)


#end of line