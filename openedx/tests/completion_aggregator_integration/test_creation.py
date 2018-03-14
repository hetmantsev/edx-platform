"""
Test creation of aggregate completions when a user works through a course.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from completion.models import BlockCompletion
from completion.test_utils import CompletionWaffleTestMixin
from completion_aggregator.models import Aggregator
import pytest

from openedx.core.djangolib.testing.utils import skip_unless_lms
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

log = logging.getLogger(__name__)


class AggregatorCompletionTestCase(CompletionWaffleTestMixin, SharedModuleStoreTestCase):

    """
    Test that aggregators are created and updated properly for earned BlockCompletions.
    """

    @classmethod
    def setUpClass(cls):
        super(AggregatorCompletionTestCase, cls).setUpClass()
        cls.course = CourseFactory.create()
        with cls.store.bulk_operations(cls.course.id):
            cls.chapter = ItemFactory.create(
                parent=cls.course,
                category="chapter",
            )
            cls.sequential = ItemFactory.create(
                parent=cls.chapter,
                category='sequential',
            )
            cls.vertical1 = ItemFactory.create(parent=cls.sequential, category='vertical')
            cls.vertical2 = ItemFactory.create(parent=cls.sequential, category='vertical')
            cls.problems = [
                ItemFactory.create(parent=cls.vertical1, category="problem"),
                ItemFactory.create(parent=cls.vertical1, category="problem"),
                ItemFactory.create(parent=cls.vertical1, category="problem"),
                ItemFactory.create(parent=cls.vertical1, category="problem"),
            ]
            cls.multiparent_problem = ItemFactory.create(parent=cls.vertical1, category="problem")
            cls.vertical2.children.append(cls.multiparent_problem.location)
            creator = UserFactory()
            cls.store.update_item(cls.vertical2, creator.id)
            cls.store.update_item(cls.course, creator.id)

    def setUp(self):
        super(AggregatorCompletionTestCase, self).setUp()
        self.override_waffle_switch(True)
        self.user = UserFactory.create()
        self.course_key = self.course.id

    def aggregator_for(self, item):
        """
        Return the aggregator for the given item, or raise an Aggregator.DoesNotExist
        """
        return Aggregator.objects.get(block_key=item.location)

    def assert_expected_values(self, values_map):
        for item in values_map:
            if values_map[item]:
                assert self.aggregator_for(item).earned == values_map[item][0]
                assert self.aggregator_for(item).possible == values_map[item][1]
            else:
                with pytest.raises(Aggregator.DoesNotExist):
                    self.aggregator_for(item)

    def test_aok(self):
        pass

    def test_marking_blocks_complete_updates_aggregators(self):
        log.info("Submitting block completion")
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.problems[0].location,
            completion=0.75,
        )
        self.assert_expected_values({
            self.vertical1: (0.75, 5.0),
            self.vertical2: (),
            self.sequential: (0.75, 6.0),
            self.chapter: (0.75, 6.0),
            self.course: (0.75, 6.0),
        })

    def test_dag_block_values_summed(self):
        log.info("Submitting block completion")
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.multiparent_problem.location,
            completion=1.0,
        )
        self.assert_expected_values({
            self.vertical1: (1.0, 5.0),
            self.vertical2: (1.0, 1.0),
            self.sequential: (2.0, 6.0),
            self.chapter: (2.0, 6.0),
            self.course: (2.0, 6.0),
        })

    def test_modify_existing_completion(self):
        log.info("Submitting block completion")
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.problems[2].location,
            completion=0.8,
        )
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.multiparent_problem.location,
            completion=0.25,
        )
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.problems[2].location,
            completion=0.5,
        )
        BlockCompletion.objects.submit_completion(
            user=self.user,
            course_key=self.course.id,
            block_key=self.multiparent_problem.location,
            completion=0.0,
        )
        # After updating already-existing completion values,
        # the new values take effect, and existing aggregators
        # still exist, even if they are empty.
        self.assert_expected_values({
            self.vertical1: (0.5, 5.0),
            self.vertical2: (0.0, 1.0),
            self.sequential: (0.5, 6.0),
            self.chapter: (0.5, 6.0),
            self.course: (0.5, 6.0),

        })
