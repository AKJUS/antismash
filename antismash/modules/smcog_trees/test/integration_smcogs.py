# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

# for test files, silence irrelevant and noisy pylint warnings
# pylint: disable=use-implicit-booleaness-not-comparison,protected-access,missing-docstring

import glob
import os
import shutil
import unittest

from helperlibs.bio import seqio
from helperlibs.wrappers.io import TemporaryDirectory

import antismash
from antismash.common import secmet
from antismash.common.test import helpers
from antismash.config import get_config, update_config, destroy_config, build_config
from antismash.detection import genefunctions
from antismash.main import read_data
from antismash.modules import smcog_trees


class Base(unittest.TestCase):
    def setUp(self):
        self.old_config = get_config().__dict__
        options = build_config(self.get_args(), isolated=True,
                               modules=antismash.get_all_modules())
        self.options = update_config(options)
        update_config({"cpus": 1})
        # prevent multiprocess testing from taking place, to stop signals
        # being caught awkwardly in the test itself

        # as smcogs_trees depends on genefunctions.smcogs' data, ensure that's ready to go
        assert genefunctions.tools.smcogs.prepare_data() == []

        assert smcog_trees.check_prereqs(self.options) == []
        assert smcog_trees.check_options(self.options) == []
        assert smcog_trees.is_enabled(self.options)

        self.record = self.build_record(helpers.get_path_to_nisin_with_detection())

    def tearDown(self):
        destroy_config()

    def get_args(self):
        return ["--minimal", "--smcog-trees"]

    def build_record(self, genbank):
        # construct a working record
        with open(genbank, encoding="utf-8") as handle:
            seq_record = seqio.read(handle, "genbank")
        record = secmet.Record.from_biopython(seq_record, taxon="bacteria")
        assert record.get_protoclusters()
        assert record.get_protocluster(0).cds_children
        return record


class TestTreeGeneration(Base):
    def get_args(self):
        return super().get_args() + ["--smcog-trees"]

    def test_trees(self):
        with TemporaryDirectory(change=True) as temp:
            # add the classifications to work with
            genefunctions.tools.smcogs.classify(self.record.get_cds_features(),
                                                self.options).add_to_record(self.record)

            results = smcog_trees.run_on_record(self.record, None, self.options)

            # test the results function properly
            json = results.to_json()
            assert smcog_trees.SMCOGTreeResults.from_json(json, self.record).to_json() == json
            regenerated = smcog_trees.regenerate_previous_results(json, self.record, self.options)
            assert isinstance(regenerated, smcog_trees.SMCOGTreeResults), json
            assert regenerated.to_json() == json

            # no files should have been written
            assert not glob.glob(os.path.join(temp, "*"))

        results.add_to_record(self.record)
        for cds in self.record.get_cds_features():
            if cds.gene_functions.get_by_tool("rule-based-clusters"):
                continue  # no sense checking, because we don't do anything with it
            if not cds.gene_functions.get_by_tool("smcogs"):
                continue
            assert cds.get_name() in results.trees
            assert cds.gene_function != secmet.qualifiers.GeneFunction.OTHER

    def test_trees_complete(self):
        expected_tree_count = 7
        with TemporaryDirectory() as output_dir:
            args = ["--minimal", "--enable-genefunctions", "--smcog-trees",
                    "--output-dir", output_dir, helpers.get_path_to_nisin_genbank()]
            options = build_config(args, isolated=True, modules=antismash.get_all_modules())
            image_path = os.path.join(output_dir, "smcogs", "*.png")

            antismash.run_antismash(helpers.get_path_to_nisin_genbank(), options)

            with open(os.path.join(output_dir, "nisin.json"), encoding="utf-8") as res_file:
                assert "antismash.modules.smcog_trees" in res_file.read()

            # ensure images are created
            tree_files = glob.glob(image_path)
            assert len(tree_files) == expected_tree_count
            # clean them up for the next part
            shutil.rmtree(os.path.join(output_dir, "smcogs"))

            # regen the results
            update_config({"reuse_results": os.path.join(output_dir, "nisin.json")})
            prior_results = read_data(None, options)
            record = prior_results.records[0]
            results = prior_results.results[0]
            tree_results = results["antismash.modules.smcog_trees"]
            smcogs_results = smcog_trees.regenerate_previous_results(tree_results, record, options)
            assert len(smcogs_results.trees) == expected_tree_count

            # while the results object is regenerated, the output images should not have been
            tree_files = glob.glob(image_path)
            assert len(tree_files) == 0

            # but those images should reappear when the write function is called
            smcogs_results.write_outputs(self.record, options)
            tree_files = glob.glob(image_path)
            assert len(tree_files) == expected_tree_count
