# Copyright 2013-2017 DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

try:
    import unittest2 as unittest
except ImportError:
    import unittest  # noqa

from cassandra.cqlengine.management import sync_table, drop_table
from cassandra.cqlengine.connection import get_connection
from cassandra.cqlengine.models import Model, columns
from cassandra.cluster import OperationTimedOut
from cassandra import InvalidRequest

from cassandra.cqlengine.query import BatchQuery

from tests.integration.cqlengine.base import BaseCassEngTestCase, BaseCassEngTestCaseWithTable, TestMultiKeyModel

from concurrent.futures import wait


class ConcurrentTests(BaseCassEngTestCaseWithTable):
    text_to_write = 'write this text'

    def test_create_async_from_model(self):
        self._write_sample_from_model()
        self._verify_reads_from_model()

    def test_create_async_from_instance(self):
        self._write_sample_from_instance()
        self._verify_reads_from_instance()

    def test_save_async(self):
        m = TestMultiKeyModel.create_async().result()

        write_futures = []
        for i in range(10):
            m.partition = i
            m.cluster = i
            m.count = 5
            m.text = self.text_to_write
            write_futures.append(m.save_async())

        self._verify_reads_from_model()

    def test_update_async(self):
        m = TestMultiKeyModel.create_async(partition=0, cluster=0, count=5, text=self.text_to_write).result()

        write_futures = []
        for i in range(10):
            m.partition = i
            m.cluster = i
            m.count = 5
            m.text = self.text_to_write
            write_futures.append(m.update_async())

        wait(write_futures)

        self._verify_reads_from_model()

    def test_update_async_modelqueryset(self):
        self._write_sample_from_model()
        write_futures = []
        for i in range(10):
            write_futures.append(TestMultiKeyModel.objects.filter(partition=i, cluster=i).
                                 update_async(count=None, text="other_text"))
        wait(write_futures)
        for i in range(10):
            result = TestMultiKeyModel.get_async(partition=i, cluster=i).result()
            self.assertEqual((result.partition, result.cluster, result.count, result.text), (i, i, None, "other_text"))

    def test_delete_async(self):
        self._write_sample_from_model()

        delete_futures = []
        for i in range(10):
            delete_futures.append(TestMultiKeyModel.objects(partition=i, cluster=i).delete_async())

        wait(delete_futures)

        read_futures = []
        for i in range(10):
            read_futures.append(TestMultiKeyModel.get_async(partition=i, cluster=i))

        for i, future in enumerate(read_futures):
            with self.assertRaises(TestMultiKeyModel.DoesNotExist):
                future.result()

    def test_delete_async_from_instance(self):
        models = []
        for i in range(10):
            models.append(TestMultiKeyModel.create_async(partition=i, cluster=i, count=5,
                                                         text=self.text_to_write).result())
        self._verify_reads_from_model()

        # None values are treated in a slightly different way
        models.append(TestMultiKeyModel.create_async(partition=11, cluster=11, count=None,
                                                     text=None).result())

        delete_futures = []
        for m in models:
            delete_futures.append(m.delete_async())

        wait(delete_futures)

        self._verify_table_is_empty()

    def test_get_all(self):
        self._write_sample_from_model()
        read_futures = self._verify_reads_from_model()

        all_the_rows = TestMultiKeyModel.get_all_async().result()
        self.assertEqual(len(all_the_rows), 10)

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertIn(result, all_the_rows)

        all_the_rows_sync = TestMultiKeyModel.get_all()
        self.assertEqual(all_the_rows, all_the_rows_sync)

    def test_read_with_small_fetch_size(self):
        self._write_sample_from_model(1000)
        session = get_connection().session
        original_fetch_size = session.default_fetch_size
        self.addCleanup(lambda : setattr(get_connection().session, "default_fetch_size", original_fetch_size))
        session.default_fetch_size = 4

        read_futures = self._verify_reads_from_model(1000)

        all_the_rows = TestMultiKeyModel.get_all_async().result()
        self.assertEqual(len(all_the_rows), 1000)

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertIn(result, all_the_rows)

        all_the_rows_sync = TestMultiKeyModel.get_all()
        self.assertEqual(all_the_rows, all_the_rows_sync)

    def test_count_async(self):
        self._write_sample_from_model()

        count_futures = []
        for i in range(10):
            count_futures.append(TestMultiKeyModel.objects(partition=i, cluster=i).count_async())

        count_all = TestMultiKeyModel.objects().count_async()

        for count_future in count_futures:
            self.assertEqual(count_future.result(), 1)
        self.assertEqual(count_all.result(), 10)

    def test_exception(self):
        # Test DoesNotExist
        read_future = TestMultiKeyModel(partition=0, cluster=0).get_async()
        with self.assertRaises(TestMultiKeyModel.DoesNotExist):
            read_future.result()

        # Test OperationTimedOut
        m = TestMultiKeyModel(partition=0, cluster=0, count=5, text=self.text_to_write)
        save_future = m.timeout(0).save_async()
        with self.assertRaises(OperationTimedOut):
            save_future.result()

        # Test server exception
        m = TestMultiKeyModel(partition=1, count=5, text=self.text_to_write)
        save_future = m.save_async() # Invalid consistency level
        with self.assertRaises(InvalidRequest):
            save_future.result()

    def test_batch(self):
        batch_futures = []
        for i in range(10):
            b = BatchQuery()
            TestMultiKeyModel.batch(b).create(partition=i, cluster=i, count=5, text=self.text_to_write)
            batch_futures.append(b.execute_async())

        wait(batch_futures)
        self._verify_reads_from_model()

        batch_futures = []
        for i in range(10):
            b = BatchQuery()
            TestMultiKeyModel.batch(b).filter(partition=i, cluster=i).delete()
            batch_futures.append(b.execute_async())

        wait(batch_futures)
        self._verify_table_is_empty()

    def test_batch_context(self):
        batch_futures = []
        for i in range(10):
            with BatchQuery() as b:
                TestMultiKeyModel.batch(b).create(partition=i, cluster=i, count=5, text=self.text_to_write)
                batch_futures.append(b.execute_async())

        wait(batch_futures)
        self._verify_reads_from_model()

        batch_futures = []
        for i in range(10):
            with BatchQuery() as b:
                TestMultiKeyModel.batch(b).filter(partition=i, cluster=i).delete()
                batch_futures.append(b.execute_async())

        wait(batch_futures)
        self._verify_table_is_empty()

    def test_batch_exception(self):
        b = BatchQuery()
        for i in range(10):
            TestMultiKeyModel.batch(b).create(partition=i, cluster=i, count=5, text=self.text_to_write)
        TestMultiKeyModel.batch(b).create(partition=11, count=5, text=self.text_to_write)
        batch_future = b.execute_async()

        with self.assertRaises(InvalidRequest):
            batch_future.result()

        self._verify_table_is_empty()

    def test_operators(self):
        pass

    def _write_sample_from_instance(self, n=10):
        write_futures = []
        for i in range(n):
            write_futures.append(TestMultiKeyModel(partition=i, cluster=i,
                                                                count=5, text=self.text_to_write).save_async())
        wait(write_futures)

    def _write_sample_from_model(self, n=10):
        write_futures = []
        for i in range(n):
            write_futures.append(TestMultiKeyModel.create_async(partition=i, cluster=i,
                                                                count=5, text=self.text_to_write))
        wait(write_futures)

    def _verify_reads_from_instance(self, n=10):
        read_futures = []
        for i in range(n):
            read_futures.append(TestMultiKeyModel.objects.filter(partition=i, cluster=i).get_async())

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertEqual((result.partition, result.cluster, result.count, result.text), (i, i, 5,
                                                                                             self.text_to_write))
        return read_futures

    def _verify_reads_from_model(self, n=10):
        read_futures = []
        for i in range(n):
            read_futures.append(TestMultiKeyModel.get_async(partition=i, cluster=i))

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertEqual((result.partition, result.cluster, result.count, result.text), (i, i, 5,
                                                                                             self.text_to_write))
        return read_futures

    def _verify_table_is_empty(self):
        all_the_rows = TestMultiKeyModel.get_all()
        self.assertEqual(len(all_the_rows), 0)


class OverrideAsyncMethodsTest(unittest.TestCase):
    text_to_write = 'write this text'

    @unittest.skip
    def test_inheritance(self):
        def raise_(self):
            raise(ValueError("Nothing can be saved"))
        saveClass = type("saveClass", (TestMultiKeyModel,),
             {"save_async": raise_})

        class saveClass(TestMultiKeyModel):
            owner_id = columns.UUID(primary_key=True)

            def save_async(self):
                raise ValueError("Cats not accepted for now")


        sync_table(saveClass)
        self.addCleanup(drop_table, saveClass)

        with self.assertRaises(ValueError):
            saveClass.create_async(partition=0, cluster=0, count=5, text=self.text_to_write).result()

        with self.assertRaises(ValueError):
            saveClass.create(partition=0, cluster=0, count=5, text=self.text_to_write)

        with self.assertRaises(ValueError):
            saveClass.save_async(partition=0, cluster=0, count=5, text=self.text_to_write).result()

        with self.assertRaises(ValueError):
            saveClass.save(partition=0, cluster=0, count=5, text=self.text_to_write)

