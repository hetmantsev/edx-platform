"""
Actions manager for transcripts ajax calls.
+++++++++++++++++++++++++++++++++++++++++++

Module do not support rollback (pressing "Cancel" button in Studio)
All user changes are saved immediately.
"""
import copy
import json
import logging
import os

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponse
from django.utils.translation import ugettext as _
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import UsageKey
from six import text_type
from edxval.api import create_or_update_video_transcript, create_external_video
from student.auth import has_course_author_access
from util.json_request import JsonResponse
from xmodule.contentstore.content import StaticContent
from xmodule.contentstore.django import contentstore
from xmodule.exceptions import NotFoundError
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.video_module.transcripts_utils import (
    clean_video_id,
    copy_or_rename_transcript,
    download_youtube_subs,
    GetTranscriptsFromYouTubeException,
    get_video_transcript_content,
    generate_subs_from_source,
    get_transcripts_from_youtube,
    manage_video_subtitles_save,
    remove_subs_from_store,
    Transcript,
    TranscriptsRequestValidationException,
    TranscriptsGenerationException,
    youtube_video_transcript_name,
)
from xmodule.video_module.transcripts_model_utils import (
    is_val_transcript_feature_enabled_for_course
)

from cms.djangoapps.contentstore.views.videos import TranscriptProvider

__all__ = [
    'upload_transcripts',
    'download_transcripts',
    'check_transcripts',
    'choose_transcripts',
    'replace_transcripts',
    'rename_transcripts',
    'save_transcripts',
]

log = logging.getLogger(__name__)


def error_response(response, message, status_code=400):
    """
    Simplify similar actions: log message and return JsonResponse with message included in response.

    By default return 400 (Bad Request) Response.
    """
    log.debug(message)
    response['status'] = message
    return JsonResponse(response, status_code)


def validate_transcript_upload_data(request):
    """
    Validates video transcript file.

    Arguments:
        request: A WSGI request's data part.

    Returns:
        Tuple containing an error and validated data
        If there is a validation error then, validated data will be empty.
    """
    error, validated_data = None, {}
    data, files = request.POST, request.FILES
    from pdb import set_trace; set_trace()
    if not data.get('locator'):
        error = _(u'Video locator is required.')
    elif 'transcript-file' not in files:
        error = _(u'A transcript file is required.')
    elif os.path.splitext(files['transcript-file'].name)[1][1:] != Transcript.SRT:
        error = _(u'This transcript file type is not supported.')

    if not error:
        try:
            item = _get_item(request, data)
            if item.category != 'video':
                error = _(u'Transcripts are supported only for "video" module.')
            else:
                validated_data.update({
                    'video': item,
                    'edx_video_id': clean_video_id(item.edx_video_id),
                    'transcript_file': files['transcript-file']
                })
        except (InvalidKeyError, ItemNotFoundError):
            error = _(u'Cannot find item by locator.')

    return error, validated_data


@login_required
def upload_transcripts(request):
    """
    Upload transcripts for current module.

    returns: response dict::

        status: 'Success' and HTTP 200 or 'Error' and HTTP 400.
        subs: Value of uploaded and saved html5 sub field in video item.
    """
    error, validated_data = validate_transcript_upload_data(request)
    if error:
        response = JsonResponse({'status': error}, status=400)
    else:
        video = validated_data['video']
        edx_video_id = validated_data['edx_video_id']
        transcript_file = validated_data['transcript_file']
        # check if we need to create an external VAL video to associate the transcript
        # and save its ID on the video component.
        if not edx_video_id:
            edx_video_id = create_external_video(display_name=u'external video')
            video.edx_video_id = edx_video_id
            video.save_with_metadata(request.user)

        try:
            # Convert 'srt' transcript into the 'sjson' and upload it to
            # configured transcript storage. For example, S3.
            sjson_subs = Transcript.convert(
                content=transcript_file.read(),
                input_format=Transcript.SRT,
                output_format=Transcript.SJSON
            )
            create_or_update_video_transcript(
                video_id=edx_video_id,
                language_code=u'en',
                metadata={
                    'provider': TranscriptProvider.CUSTOM,
                    'file_format': Transcript.SJSON,
                    'language_code': u'en'
                },
                file_data=ContentFile(sjson_subs),
            )
            response = JsonResponse({'edx_video_id': edx_video_id}, status=200)

        except (TranscriptsGenerationException, UnicodeDecodeError):

            response = JsonResponse({
                'status': _(u'There is a problem with this transcript file. Try to upload a different file.')
            }, status=400)

    return response


@login_required
def download_transcripts(request):
    """
    Passes to user requested transcripts file.

    Raises Http404 if unsuccessful.
    """
    locator = request.GET.get('locator')
    subs_id = request.GET.get('subs_id')
    if not locator:
        log.debug('GET data without "locator" property.')
        raise Http404

    try:
        item = _get_item(request, request.GET)
    except (InvalidKeyError, ItemNotFoundError):
        log.debug("Can't find item by locator.")
        raise Http404

    if item.category != 'video':
        log.debug('transcripts are supported only for video" modules.')
        raise Http404

    try:
        if not subs_id:
            raise NotFoundError

        filename = subs_id
        content_location = StaticContent.compute_location(
            item.location.course_key,
            'subs_{filename}.srt.sjson'.format(filename=filename),
        )
        input_format = Transcript.SJSON
        transcript_content = contentstore().find(content_location).data
    except NotFoundError:
        # Try searching in VAL for the transcript as a last resort
        transcript = None
        if is_val_transcript_feature_enabled_for_course(item.location.course_key):
            transcript = get_video_transcript_content(edx_video_id=item.edx_video_id, language_code=u'en')

        if not transcript:
            raise Http404

        name_and_extension = os.path.splitext(transcript['file_name'])
        filename, input_format = name_and_extension[0], name_and_extension[1][1:]
        transcript_content = transcript['content']

    # convert sjson content into srt format.
    transcript_content = Transcript.convert(transcript_content, input_format=input_format, output_format=Transcript.SRT)
    if not transcript_content:
        raise Http404

    # Construct an HTTP response
    response = HttpResponse(transcript_content, content_type='application/x-subrip; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="{filename}.srt"'.format(filename=filename)
    return response


@login_required
def check_transcripts(request):
    """
    Check state of transcripts availability.

    request.GET['data'] has key `videos`, which can contain any of the following::

        [
            {u'type': u'youtube', u'video': u'OEoXaMPEzfM', u'mode': u'youtube'},
            {u'type': u'html5',    u'video': u'video1',             u'mode': u'mp4'}
            {u'type': u'html5',    u'video': u'video2',             u'mode': u'webm'}
        ]
        `type` is youtube or html5
        `video` is html5 or youtube video_id
        `mode` is youtube, ,p4 or webm

    Returns transcripts_presence dict::

        html5_local: list of html5 ids, if subtitles exist locally for them;
        is_youtube_mode: bool, if we have youtube_id, and as youtube mode is of higher priority, reflect this with flag;
        youtube_local: bool, if youtube transcripts exist locally;
        youtube_server: bool, if youtube transcripts exist on server;
        youtube_diff: bool, if youtube transcripts exist on youtube server, and are different from local youtube ones;
        current_item_subs: string, value of item.sub field;
        status: string, 'Error' or 'Success';
        subs: string, new value of item.sub field, that should be set in module;
        command: string, action to front-end what to do and what to show to user.
    """
    transcripts_presence = {
        'html5_local': [],
        'html5_equal': False,
        'is_youtube_mode': False,
        'youtube_local': False,
        'youtube_server': False,
        'youtube_diff': True,
        'current_item_subs': None,
        'status': 'Error',
    }
    try:
        __, videos, item = _validate_transcripts_data(request)
    except TranscriptsRequestValidationException as e:
        return error_response(transcripts_presence, text_type(e))

    transcripts_presence['status'] = 'Success'

    filename = 'subs_{0}.srt.sjson'.format(item.sub)
    content_location = StaticContent.compute_location(item.location.course_key, filename)
    try:
        local_transcripts = contentstore().find(content_location).data
        transcripts_presence['current_item_subs'] = item.sub
    except NotFoundError:
        pass

    # Check for youtube transcripts presence
    youtube_id = videos.get('youtube', None)
    if youtube_id:
        transcripts_presence['is_youtube_mode'] = True

        # youtube local
        filename = 'subs_{0}.srt.sjson'.format(youtube_id)
        content_location = StaticContent.compute_location(item.location.course_key, filename)
        try:
            local_transcripts = contentstore().find(content_location).data
            transcripts_presence['youtube_local'] = True
        except NotFoundError:
            log.debug("Can't find transcripts in storage for youtube id: %s", youtube_id)

        # youtube server
        youtube_text_api = copy.deepcopy(settings.YOUTUBE['TEXT_API'])
        youtube_text_api['params']['v'] = youtube_id
        youtube_transcript_name = youtube_video_transcript_name(youtube_text_api)
        if youtube_transcript_name:
            youtube_text_api['params']['name'] = youtube_transcript_name
        youtube_response = requests.get('http://' + youtube_text_api['url'], params=youtube_text_api['params'])

        if youtube_response.status_code == 200 and youtube_response.text:
            transcripts_presence['youtube_server'] = True
        #check youtube local and server transcripts for equality
        if transcripts_presence['youtube_server'] and transcripts_presence['youtube_local']:
            try:
                youtube_server_subs = get_transcripts_from_youtube(
                    youtube_id,
                    settings,
                    item.runtime.service(item, "i18n")
                )
                if json.loads(local_transcripts) == youtube_server_subs:  # check transcripts for equality
                    transcripts_presence['youtube_diff'] = False
            except GetTranscriptsFromYouTubeException:
                pass

    # Check for html5 local transcripts presence
    html5_subs = []
    for html5_id in videos['html5']:
        filename = 'subs_{0}.srt.sjson'.format(html5_id)
        content_location = StaticContent.compute_location(item.location.course_key, filename)
        try:
            html5_subs.append(contentstore().find(content_location).data)
            transcripts_presence['html5_local'].append(html5_id)
        except NotFoundError:
            log.debug("Can't find transcripts in storage for non-youtube video_id: %s", html5_id)
        if len(html5_subs) == 2:  # check html5 transcripts for equality
            transcripts_presence['html5_equal'] = json.loads(html5_subs[0]) == json.loads(html5_subs[1])

    command, subs_to_use = _transcripts_logic(transcripts_presence, videos)
    if command == 'not_found':
        # Try searching in VAL for the transcript as a last resort
        if is_val_transcript_feature_enabled_for_course(item.location.course_key):
            video_transcript = get_video_transcript_content(edx_video_id=item.edx_video_id, language_code=u'en')
            command = 'found' if video_transcript else command

    transcripts_presence.update({
        'command': command,
        'subs': subs_to_use,
    })
    return JsonResponse(transcripts_presence)


def _transcripts_logic(transcripts_presence, videos):
    """
    By `transcripts_presence` content, figure what show to user:

    returns: `command` and `subs`.

    `command`: string,  action to front-end what to do and what show to user.
    `subs`: string, new value of item.sub field, that should be set in module.

    `command` is one of::

        replace: replace local youtube subtitles with server one's
        found: subtitles are found
        import: import subtitles from youtube server
        choose: choose one from two html5 subtitles
        not found: subtitles are not found
    """
    command = None

    # new value of item.sub field, that should be set in module.
    subs = ''

    # youtube transcripts are of high priority than html5 by design
    if (
            transcripts_presence['youtube_diff'] and
            transcripts_presence['youtube_local'] and
            transcripts_presence['youtube_server']):  # youtube server and local exist
        command = 'replace'
        subs = videos['youtube']
    elif transcripts_presence['youtube_local']:  # only youtube local exist
        command = 'found'
        subs = videos['youtube']
    elif transcripts_presence['youtube_server']:  # only youtube server exist
        command = 'import'
    else:  # html5 part
        if transcripts_presence['html5_local']:  # can be 1 or 2 html5 videos
            if len(transcripts_presence['html5_local']) == 1 or transcripts_presence['html5_equal']:
                command = 'found'
                subs = transcripts_presence['html5_local'][0]
            else:
                command = 'choose'
                subs = transcripts_presence['html5_local'][0]
        else:  # html5 source have no subtitles
            # check if item sub has subtitles
            if transcripts_presence['current_item_subs'] and not transcripts_presence['is_youtube_mode']:
                log.debug("Command is use existing %s subs", transcripts_presence['current_item_subs'])
                command = 'use_existing'
            else:
                command = 'not_found'
    log.debug(
        "Resulted command: %s, current transcripts: %s, youtube mode: %s",
        command,
        transcripts_presence['current_item_subs'],
        transcripts_presence['is_youtube_mode']
    )
    return command, subs


@login_required
def choose_transcripts(request):
    """
    Replaces html5 subtitles, presented for both html5 sources, with chosen one.

    Code removes rejected html5 subtitles and updates sub attribute with chosen html5_id.

    It does nothing with youtube id's.

    Returns: status `Success` and resulted item.sub value or status `Error` and HTTP 400.
    """
    response = {
        'status': 'Error',
        'subs': '',
    }

    try:
        data, videos, item = _validate_transcripts_data(request)
    except TranscriptsRequestValidationException as e:
        return error_response(response, text_type(e))

    html5_id = data.get('html5_id')  # html5_id chosen by user

    # find rejected html5_id and remove appropriate subs from store
    html5_id_to_remove = [x for x in videos['html5'] if x != html5_id]
    if html5_id_to_remove:
        remove_subs_from_store(html5_id_to_remove, item)

    if item.sub != html5_id:  # update sub value
        item.sub = html5_id
        item.save_with_metadata(request.user)
    response = {
        'status': 'Success',
        'subs': item.sub,
    }
    return JsonResponse(response)


@login_required
def replace_transcripts(request):
    """
    Replaces all transcripts with youtube ones.

    Downloads subtitles from youtube and replaces all transcripts with downloaded ones.

    Returns: status `Success` and resulted item.sub value or status `Error` and HTTP 400.
    """
    response = {'status': 'Error', 'subs': ''}

    try:
        __, videos, item = _validate_transcripts_data(request)
    except TranscriptsRequestValidationException as e:
        return error_response(response, text_type(e))

    youtube_id = videos['youtube']
    if not youtube_id:
        return error_response(response, 'YouTube id {} is not presented in request data.'.format(youtube_id))

    try:
        download_youtube_subs(youtube_id, item, settings)
    except GetTranscriptsFromYouTubeException as e:
        return error_response(response, text_type(e))

    item.sub = youtube_id
    item.save_with_metadata(request.user)
    response = {
        'status': 'Success',
        'subs': item.sub,
    }
    return JsonResponse(response)


def _validate_transcripts_data(request):
    """
    Validates, that request contains all proper data for transcripts processing.

    Returns tuple of 3 elements::

        data: dict, loaded json from request,
        videos: parsed `data` to useful format,
        item:  video item from storage

    Raises `TranscriptsRequestValidationException` if validation is unsuccessful
    or `PermissionDenied` if user has no access.
    """
    data = json.loads(request.GET.get('data', '{}'))
    if not data:
        raise TranscriptsRequestValidationException(_('Incoming video data is empty.'))

    try:
        item = _get_item(request, data)
    except (InvalidKeyError, ItemNotFoundError):
        raise TranscriptsRequestValidationException(_("Can't find item by locator."))

    if item.category != 'video':
        raise TranscriptsRequestValidationException(_('Transcripts are supported only for "video" modules.'))

    # parse data form request.GET.['data']['video'] to useful format
    videos = {'youtube': '', 'html5': {}}
    for video_data in data.get('videos'):
        if video_data['type'] == 'youtube':
            videos['youtube'] = video_data['video']
        else:  # do not add same html5 videos
            if videos['html5'].get('video') != video_data['video']:
                videos['html5'][video_data['video']] = video_data['mode']

    return data, videos, item


@login_required
def rename_transcripts(request):
    """
    Create copies of existing subtitles with new names of HTML5 sources.

    Old subtitles are not deleted now, because we do not have rollback functionality.

    If succeed, Item.sub will be chosen randomly from html5 video sources provided by front-end.
    """
    response = {'status': 'Error', 'subs': ''}

    try:
        __, videos, item = _validate_transcripts_data(request)
    except TranscriptsRequestValidationException as e:
        return error_response(response, text_type(e))

    old_name = item.sub

    for new_name in videos['html5'].keys():  # copy subtitles for every HTML5 source
        try:
            # updates item.sub with new_name if it is successful.
            copy_or_rename_transcript(new_name, old_name, item, user=request.user)
        except NotFoundError:
            # subtitles file `item.sub` is not presented in the system. Nothing to copy or rename.
            error_response(response, "Can't find transcripts in storage for {}".format(old_name))

    response['status'] = 'Success'
    response['subs'] = item.sub  # item.sub has been changed, it is not equal to old_name.
    log.debug("Updated item.sub to %s", item.sub)
    return JsonResponse(response)


@login_required
def save_transcripts(request):
    """
    Saves video module with updated values of fields.

    Returns: status `Success` or status `Error` and HTTP 400.
    """
    response = {'status': 'Error'}

    data = json.loads(request.GET.get('data', '{}'))
    if not data:
        return error_response(response, 'Incoming video data is empty.')

    try:
        item = _get_item(request, data)
    except (InvalidKeyError, ItemNotFoundError):
        return error_response(response, "Can't find item by locator.")

    metadata = data.get('metadata')
    if metadata is not None:
        new_sub = metadata.get('sub')

        for metadata_key, value in metadata.items():
            setattr(item, metadata_key, value)

        item.save_with_metadata(request.user)  # item becomes updated with new values

        if new_sub:
            manage_video_subtitles_save(item, request.user)
        else:
            # If `new_sub` is empty, it means that user explicitly does not want to use
            # transcripts for current video ids and we remove all transcripts from storage.
            current_subs = data.get('current_subs')
            if current_subs is not None:
                for sub in current_subs:
                    remove_subs_from_store(sub, item)

        response['status'] = 'Success'

    return JsonResponse(response)


def _get_item(request, data):
    """
    Obtains from 'data' the locator for an item.
    Next, gets that item from the modulestore (allowing any errors to raise up).
    Finally, verifies that the user has access to the item.

    Returns the item.
    """
    usage_key = UsageKey.from_string(data.get('locator'))
    # This is placed before has_course_author_access() to validate the location,
    # because has_course_author_access() raises  r if location is invalid.
    item = modulestore().get_item(usage_key)

    # use the item's course_key, because the usage_key might not have the run
    if not has_course_author_access(request.user, item.location.course_key):
        raise PermissionDenied()

    return item
