# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

"""HTML output format module

"""

import argparse
import glob
import logging
import os
import re
import shutil
import stat
from typing import Dict, List, Optional
import warnings

import sass

from antismash.common import html_renderer, path
from antismash.common.module_results import ModuleResults
from antismash.common.secmet import Record
from antismash.custom_typing import AntismashModule
from antismash.config import ConfigType
from antismash.config.args import ModuleArgs
from antismash.outputs.html.generator import generate_webpage, find_local_antismash_js_path

NAME = "html"
SHORT_DESCRIPTION = "HTML output"


def get_arguments() -> ModuleArgs:
    """ Builds the arguments for the HMTL output module """
    args = ModuleArgs("Output options", "html", enabled_by_default=True)
    args.add_option("--html-title",
                    dest="html_title",
                    type=str,
                    default="",
                    help=("Custom title for the HTML output page "
                          "(default is input filename)."))
    args.add_option("--html-description",
                    dest="html_description",
                    type=str,
                    default="",
                    help="Custom description to add to the output.")
    args.add_option("--html-start-compact",
                    dest="html_start_compact",
                    action='store_true',
                    default=False,
                    help="Use compact view by default for overview page.")
    args.add_option("--html-ncbi-context",
                    dest="html_ncbi_context",
                    action=argparse.BooleanOptionalAction,
                    default=False,
                    help="Show NCBI genomic context links for genes (default: %(default)s).")
    return args


def prepare_data(_logging_only: bool = False) -> List[str]:
    """ Rebuild any dynamically buildable data """
    flavours = ["bacteria", "fungi", "plants"]

    with path.changed_directory(path.get_full_path(__file__, "css")):
        built_files = [os.path.abspath(f"{flavour}.css") for flavour in flavours]

        if path.is_outdated(built_files, glob.glob("*.scss")):
            logging.info("CSS files out of date, rebuilding")

            for flavour in flavours:
                target = f"{flavour}.css"
                source = f"{flavour}.scss"
                assert os.path.exists(source), flavour
                result = sass.compile(filename=source, output_style="compact")
                with open(target, "w", encoding="utf-8") as out:
                    out.write(result)
    return []


def check_prereqs(_options: ConfigType) -> List[str]:
    """ Check prerequisites """
    return prepare_data()


def check_options(_options: ConfigType) -> List[str]:
    """ Check options, but none to check """
    return []


def is_enabled(options: ConfigType) -> bool:
    """ Is the HMTL module enabled (currently always enabled) """
    return options.html_enabled or not options.minimal


def write(records: List[Record], results: List[Dict[str, ModuleResults]],
          options: ConfigType, all_modules: List[AntismashModule]) -> None:
    """ Writes all results to a webpage, where applicable. Writes to options.output_dir

        Arguments:
            records: the list of Records for which results exist
            results: a list of dictionaries containing all module results for records
            options: antismash config object

        Returns:
            None
    """
    output_dir = options.output_dir

    copy_template_dir('css', output_dir, pattern=f"{options.taxon}.css")
    copy_template_dir('js', output_dir)
    # if there wasn't an antismash.js in the JS dir, fall back to one in databases
    local_path = os.path.join(output_dir, "js", "antismash.js")
    if not os.path.exists(local_path):
        js_path = find_local_antismash_js_path(options)
        if js_path:
            logging.debug("Results page using antismash.js from local copy: %s", js_path)
            shutil.copy(js_path, os.path.join(output_dir, "js", "antismash.js"))
    # and if it's still not there, that's fine, it'll use a web-accessible URL
    if not os.path.exists(local_path):
        logging.debug("Results page using antismash.js from remote host")

    copy_template_dir('images', output_dir)

    with open(os.path.join(options.output_dir, "index.html"), "w", encoding="utf-8") as result_file:
        content = generate_webpage(records, results, options, all_modules)
        # strip all leading whitespace and blank lines, as they're meaningless to HTML
        content = re.sub("^( *|$)", "", content, flags=re.M)
        result_file.write(content)


def copy_template_dir(template: str, output_dir: str, pattern: Optional[str] = None) -> None:
    """ Copy files from a template directory to the output directory, removes
        any existing directory first. If pattern is supplied, only files within
        the template directory that match the template will be copied.

        Arguments:
            template: the source directory
            output_dir: the target directory
            pattern: a pattern to restrict to, if given

        Returns:
            None
    """
    target_dir = os.path.join(output_dir, template)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    if pattern:
        os.makedirs(target_dir)
        for filename in glob.glob(path.get_full_path(__file__, template, pattern)):
            if os.path.isdir(filename):
                shutil.copytree(filename, target_dir)
            else:
                shutil.copy2(filename, target_dir)
    else:
        shutil.copytree(path.get_full_path(__file__, template), target_dir)

    # if the source tree has some directories without write permissions
    # then the output directories will also have no write permissions, which
    # will error out when any extra files are written
    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    os.chmod(output_dir, mode)
    for root, dirs, _files in os.walk(output_dir):
        for subdir in dirs:
            os.chmod(os.path.join(root, subdir), mode)
