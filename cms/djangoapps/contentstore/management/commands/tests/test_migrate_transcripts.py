"""
Test for course transcript migration.
"""

from django.test import TestCase
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from django.core.management import call_command, CommandError
from edxval.api import get_videos_for_course
from xmodule.video_module.transcripts_utils import download_youtube_subs, save_to_store
from datetime import datetime

import pytz
from edxval import api as api




SRT_FILEDATA = '''
0
00:00:00,270 --> 00:00:02,720
sprechen sie deutsch?

1
00:00:02,720 --> 00:00:05,430
Ja, ich spreche Deutsch
'''

CRO_SRT_FILEDATA = '''
0
00:00:00,270 --> 00:00:02,720
Dobar dan!

1
00:00:02,720 --> 00:00:05,430
Kako ste danas?
'''


VIDEO_DICT_STAR = dict(
    client_video_id="TWINKLE TWINKLE",
    duration=42.0,
    edx_video_id="test_edx_video_id",
    status="upload",
)


class TestArgParsing(TestCase):
    """
    Tests for parsing arguments for the `migrate_transcripts` management command
    """
    def setUp(self):
        super(TestArgParsing, self).setUp()

    def test_no_args(self):
        errstring = "Error: too few arguments"
        with self.assertRaisesRegexp(CommandError, errstring):
            call_command('migrate_transcripts')

    def test_invalid_course(self):
        with self.assertRaises(CommandError):
            call_command('migrate_transcripts', "invalid-course")



class MigrateTranscripts(ModuleStoreTestCase):
    """
    Tests migrating video transcripts in courses from contentstore to S3
    """
    def setUp(self):
        """ Common setup. """
        super(MigrateTranscripts, self).setUp()
        self.store = modulestore()._get_modulestore_by_type(ModuleStoreEnum.Type.mongo)

        self.course = CourseFactory.create()

        video_sample_xml = '''
            <video display_name="Test Video"
                   youtube="1.0:p2Q6BrNhdh8,0.75:izygArpw-Qo,1.25:1EeWXzPdhSA,1.5:rABDYkeK0x8"
                   show_captions="false"
                   download_track="false"
                   start_time="00:00:01"
                   download_video="false"
                   end_time="00:01:00">
              <source src="http://www.example.com/source.mp4"/>
              <track src="http://www.example.com/track"/>
              <handout src="http://www.example.com/handout"/>
              <transcript language="ge" src="subs_grmtran1.srt" />
              <transcript language="hr" src="subs_croatian1.srt" />
            </video>
        '''
        self.video_descriptor = ItemFactory.create(
            parent_location=self.course.location, category='video',
            data={'data': video_sample_xml}
        )

        self.video_descriptor.edx_video_id = 'test_edx_video_id'

        save_to_store(SRT_FILEDATA, "subs_grmtran1.srt", 'text/srt', self.video_descriptor.location)
        save_to_store(CRO_SRT_FILEDATA, "subs_croatian1.srt", 'text/srt', self.video_descriptor.location)

        created = datetime.now(pytz.utc)
        video = {
            "edx_video_id": "test_edx_video_id",
            "client_video_id": "test1.mp4",
            "duration": 42.0,
            "status": "upload",
            "courses": [unicode(self.course.id)],
            "encoded_videos": [],
            "created": created
        }

        api.create_video(video)


    def test_migrated_transcripts_count(self):

        # check that transcript does not exist

        languages = api.get_available_transcript_languages(self.video_descriptor.edx_video_id)

        self.assertEqual(len(languages), 0)

        # now call migrate_transcripts command and check the transcript integrity

        call_command('migrate_transcripts', '--all-courses', '--force-update')

        languages = api.get_available_transcript_languages(self.video_descriptor.edx_video_id)
        self.assertItemsEqual(languages, ['ge', 'hr'])
#        self.assertEqual(len(languages), 2)



    def test_migrates_transcripts_integrity(self):
        """
        Test migrating transcripts
        """

        translations = self.video_descriptor.available_translations(self.video_descriptor.get_transcripts_info())
        self.assertItemsEqual(translations, ['hr', 'ge'])

        # now call migrate_transcripts command and check the transcript integrity

        call_command('migrate_transcripts', '--all-courses', '--force-update')

        languages = api.get_available_transcript_languages(self.video_descriptor.edx_video_id)

        self.assertItemsEqual(languages, ['hr', 'ge'])

        self.assertEqual(api.get_video_transcript_content('hr', self.video_descriptor.edx_video_id), CRO_SRT_FILEDATA)
        self.assertEqual(api.get_video_transcript_content('ge', self.video_descriptor.edx_video_id), SRT_FILEDATA)


