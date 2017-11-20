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

from cassandra.cqlengine.management import sync_table, drop_table

from tests.integration.cqlengine.base import BaseCassEngTestCase, TestMultiKeyModel

from concurrent.futures import wait

class BaseAsyncTests(BaseCassEngTestCase):
    text_to_write = 'write this text'

    @classmethod
    def setUpClass(cls):
        super(BaseAsyncTests, cls).setUpClass()
        sync_table(TestMultiKeyModel)

    @classmethod
    def tearDownClass(cls):
        super(BaseAsyncTests, cls).tearDownClass()
        drop_table(TestMultiKeyModel)

    def test_create_async(self):
        self._write_sample()
        self._verify_reads()

    def test_save_async(self):
        m = TestMultiKeyModel.create_async().result()

        write_futures = []
        for i in range(10):
            m.partition = i
            m.cluster = i
            m.count = 5
            m.text = self.text_to_write
            write_futures.append(m.save_async())

        self._verify_reads()

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

        self._verify_reads()

    def test_delete_async(self):
        self._write_sample()

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

    def test_get_all(self):
        self._write_sample()

        all_the_rows = TestMultiKeyModel.get_all_async().result()
        self.assertEqual(len(all_the_rows), 10)

        read_futures = self._verify_reads()

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertIn(result, all_the_rows)

    def test_count_async(self):
        self._write_sample()

        count_futures = []
        for i in range(10):
            count_futures.append(TestMultiKeyModel.objects(partition=i, cluster=i).count_async())

        count_all = TestMultiKeyModel.objects().count_async()

        for count_future in count_futures:
            self.assertEqual(count_future.result(), 1)
        self.assertEqual(count_all.result(), 10)

    def _write_sample(self):
        write_futures = []
        for i in range(10):
            write_futures.append(TestMultiKeyModel.create_async(partition=i, cluster=i,
                                                                count=5, text=self.text_to_write))
        wait(write_futures)

    def _verify_reads(self):
        read_futures = []
        for i in range(10):
            read_futures.append(TestMultiKeyModel.get_async(partition=i, cluster=i))

        for i, future in enumerate(read_futures):
            result = future.result()
            self.assertEqual((result.partition, result.cluster, result.count, result.text), (i, i, 5,
                                                                                             self.text_to_write))
        return read_futures
