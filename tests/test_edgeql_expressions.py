##
# Copyright (c) 2016 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


import os.path
import unittest

from edgedb.lang.common import datetime
from edgedb.client import exceptions as exc
from edgedb.server import _testbase as tb


class TestExpressions(tb.QueryTestCase):
    SCHEMA = os.path.join(os.path.dirname(__file__), 'schemas',
                          'queries.eschema')

    SETUP = """
    """

    TEARDOWN = """
    """

    async def test_edgeql_expression01(self):
        await self.assert_query_result(r"""
            SELECT 40 + 2;
            SELECT 40 - 2;
            SELECT 40 * 2;
            SELECT 40 / 2;
            SELECT 40 % 2;
            """, [
                [42],
                [38],
                [80],
                [20],
                [0],
            ])

    @unittest.expectedFailure
    async def test_edgeql_expression02(self):
        await self.assert_query_result(r"""
            SELECT 40 ** 2;
            """, [
                [1600],
            ])

    async def test_edgeql_expression03(self):
        await self.assert_query_result(r"""
            SELECT 40 < 2;
            SELECT 40 > 2;
            SELECT 40 <= 2;
            SELECT 40 >= 2;
            SELECT 40 = 2;
            SELECT 40 != 2;
            """, [
                [False],
                [True],
                [False],
                [True],
                [False],
                [True],
            ])

    async def test_edgeql_expression04(self):
        await self.assert_query_result(r"""
            SELECT -1 + 2 * 3 - 5 - 6.0 / 2;
            SELECT
                -1 + 2 * 3 - 5 - 6.0 / 2 > 0
                OR 25 % 4 = 3 AND 42 IN (12, 42, 14);
            SELECT (-1 + 2) * 3 - (5 - 6.0) / 2;
            SELECT
                ((-1 + 2) * 3 - (5 - 6.0) / 2 > 0 OR 25 % 4 = 3)
                AND 42 IN (12, 42, 14);
            """, [
                [-3],
                [False],
                [3.5],
                [True],
            ])

    async def test_edgeql_paths_01(self):
        cases = [
            "Issue.owner.name",
            "`Issue`.`owner`.`name`",
            "Issue.(test::owner).name",
            "`Issue`.(`test`::`owner`).`name`",
            "Issue.(owner).(name)",
            "test::`Issue`.(`test`::`owner`).`name`",
            "Issue.((owner)).(((test::name)))",
        ]

        for case in cases:
            await self.con.execute('''
                USING MODULE test
                SELECT
                    Issue {
                        test::number
                    }
                WHERE
                    %s = 'Elvis';
            ''' % (case,))

    async def test_edgeql_polymorphic_01(self):
        await self.con.execute(r"""
            USING MODULE test
            SELECT Text {
                Issue.number,
                (Issue).related_to,
                (Issue).((`priority`)),
                test::Comment.owner: {
                    name
                }
            };
        """)

        await self.con.execute(r"""
            USING MODULE test
            SELECT Owned {
                Named.name
            };
        """)

    async def test_edgeql_cast01(self):
        await self.assert_query_result(r"""
            SELECT <std::str>123;
            SELECT <std::int>"123";
            SELECT <std::str>123 + 'qw';
            SELECT <std::int>"123" + 9000;
            SELECT <std::int>"123" * 100;
            SELECT <std::str>(123 * 2);
            """, [
                ['123'],
                [123],
                ['123qw'],
                [9123],
                [12300],
                ['246'],
            ])

    async def test_edgeql_cast02(self):
        # testing precedence of casting vs. multiplication
        #
        with self.assertRaisesRegex(
                exc._base.UnknownEdgeDBError,
                r'operator does not exist: text \* integer'):
            await self.con.execute("""
                SELECT <std::str>123 * 2;
            """)

    async def test_edgeql_cast03(self):
        await self.assert_query_result(r"""
            SELECT <std::str><std::int><std::float>'123.45' + 'foo';
            """, [
                ['123foo'],
            ])

    @unittest.expectedFailure
    async def test_edgeql_list01(self):
        await self.assert_query_result(r"""
            SELECT <list<std::int>> (1,);
            SELECT <list<std::int>> (1, 2, 3, 4, 5);
            """, [
                [[1]],
                [[1, 2, 3, 4, 5]],
            ])