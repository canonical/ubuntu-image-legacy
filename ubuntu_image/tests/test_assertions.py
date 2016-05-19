from ubuntu_image.assertions import ModelAssertion
from unittest import TestCase


fake_model_assertion = """
type: model
authority-id: nobody
series: 16
brand-id: zygoon
model: kvm-demo
os: ubuntu-core
architecture: amd64
kernel: canonical-pc-linux
gadget: canonical-pc
required-snaps: links
# preinstalled-snaps: a, b
# prefetched-snaps: docker
body-size: 0
"""
# TODO: add a fake body and signature once the parser understands it


two_records_assertion = """
type: model

authority-id: nobody
"""


class TestModelAssertion(TestCase):
    def test_smoke(self):
        model = ModelAssertion.from_string(fake_model_assertion)
        self.assertEqual(model.type, 'model')
        self.assertEqual(model.authority_id, 'nobody')
        self.assertEqual(model.series, '16')
        self.assertEqual(model.brand_id, 'zygoon')
        self.assertEqual(model.os, 'ubuntu-core')
        self.assertEqual(model.architecture, 'amd64')
        self.assertEqual(model.kernel, 'canonical-pc-linux')
        self.assertEqual(model.gadget, 'canonical-pc')
        self.assertEqual(model.required_snaps, 'links')

    def test_two_records(self):
        self.assertRaises(ValueError,
                          ModelAssertion.from_string,
                          two_records_assertion)

    def test_header_repr(self):
        self.assertEqual(repr(ModelAssertion.type), "Header('type')")
