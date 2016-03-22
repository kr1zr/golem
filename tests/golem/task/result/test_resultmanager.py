import os
import unittest
import uuid

from golem.resource.dirmanager import DirManager
from golem.resource.ipfs.resourcesmanager import IPFSResourceManager
from golem.task.result.resultmanager import EncryptedResultPackageManager
from golem.task.result.resultpackage import ExtractedPackage
from golem.task.taskbase import result_types
from golem.tools.testdirfixture import TestDirFixture


@unittest.skip("Helper class")
class MockNode:
    def __init__(self, name, key=None):
        if not key:
            key = uuid.uuid4()

        self.node_name = name
        self.key = key

@unittest.skip("Helper class")
class MockTaskResult:
    def __init__(self, task_id, result, result_type=None, owner_key_id=None):
        if not result_type:
            result_type = result_types['files']
        if not owner_key_id:
            owner_key_id = str(uuid.uuid4())

        self.task_id = task_id
        self.subtask_id = task_id
        self.result = result
        self.result_type = result_type
        self.owner_key_id = owner_key_id
        self.owner = str(uuid.uuid4())

class TestEncryptedResultPackageManager(TestDirFixture):

    node_name = 'test_suite'
    task_id = 'deadbeef-deadbeef'

    class TestPackageCreator(object):
        @staticmethod
        def create(result_manager, node_name, task_id):
            rm = result_manager.resource_manager
            res_dir = rm.get_resource_dir(task_id)

            out_file = os.path.join(res_dir, 'out_file')
            out_dir = os.path.join(res_dir, 'out_dir')
            out_dir_file = os.path.join(out_dir, 'dir_file')
            files = [out_file, out_dir_file]

            with open(out_file, 'w') as f:
                f.write("File contents")

            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)

            with open(out_dir_file, 'w') as f:
                f.write("Dir file contents")

            rm.add_resources(files, task_id)

            secret = result_manager.gen_secret()
            mock_node = MockNode(node_name)
            mock_task_result = MockTaskResult(task_id, files)

            return result_manager.create(mock_node,
                                         mock_task_result,
                                         secret), secret

    def setUp(self):
        TestDirFixture.setUp(self)

        self.dir_manager = DirManager(self.path, self.node_name)
        self.resource_manager = IPFSResourceManager(self.dir_manager, self.node_name,
                                                    resource_dir_method=self.dir_manager.get_task_output_dir)

    def testGenSecret(self):
        manager = EncryptedResultPackageManager(self.resource_manager)
        secret = manager.gen_secret()

        self.assertIsInstance(secret, basestring)
        secret_len = len(secret)
        s_min = EncryptedResultPackageManager.min_secret_len
        s_max = EncryptedResultPackageManager.max_secret_len
        self.assertTrue(s_min <= secret_len <= s_max)

    def testCreate(self):
        manager = EncryptedResultPackageManager(self.resource_manager)
        data, secret = self.TestPackageCreator.create(manager,
                                                      self.node_name,
                                                      self.task_id)
        path, multihash = data

        self.assertIsInstance(path, basestring)
        self.assertTrue(os.path.isfile(path))

    def testExtract(self):
        manager = EncryptedResultPackageManager(self.resource_manager)
        data, secret = self.TestPackageCreator.create(manager,
                                                      self.node_name,
                                                      self.task_id)
        path, multihash = data

        extracted = manager.extract(path, secret)
        self.assertIsInstance(extracted, ExtractedPackage)

        for f in extracted.files:
            self.assertTrue(os.path.exists(os.path.join(extracted.files_dir, f)))
