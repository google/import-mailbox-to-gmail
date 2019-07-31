#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Import mbox files to a specified label for many users.

Liron Newman lironn@google.com

Copyright 2015 Google Inc. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import base64
import io
import json
import logging
import logging.handlers
import mailbox
import os
import sys

from apiclient import discovery
from apiclient.http import set_user_agent
import httplib2
from apiclient.http import MediaIoBaseUpload
from oauth2client.service_account import ServiceAccountCredentials
import oauth2client.tools
import OpenSSL  # Required by Google API library, but not checked by it

APPLICATION_NAME = 'import-mailbox-to-gmail'
APPLICATION_VERSION = '1.5'

SCOPES = ['https://www.googleapis.com/auth/gmail.insert',
          'https://www.googleapis.com/auth/gmail.labels']


parser = argparse.ArgumentParser(
    description='Import mbox files to a specified label for many users.',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    parents=[oauth2client.tools.argparser],
    epilog=
    """
 * The directory needs to have a subdirectory for each user (with the full
   email address as the name), and in it there needs to be a separate .mbox
   file for each label. File names must end in .mbox.

 * Filename format: <user@domain.com>/<labelname>.mbox.
   Example: joe@mycompany.com/Migrated messages.mbox - This is a file named
   "Migrated messages.mbox" in the "joe@mycompany.com" subdirectory.
   It will be imported into joe@mycompany.com's Gmail account under the
   "Migrated messages" label.

 * See the README at https://goo.gl/JnFt0x for more usage information.
""")
parser.add_argument(
    '--json',
    required=True,
    help='Path to the JSON key file from https://console.developers.google.com')
parser.add_argument(
    '--dir',
    required=True,
    help=
    'Path to the directory that contains user directories with mbox files to '
    'import')
parser.add_argument(
    '--no-fix-msgid',
    dest='fix_msgid',
    required=False,
    action='store_false',
    help=
    "Don't fix Message-ID headers that are missing brackets "
    "(default: fix them)")
parser.add_argument(
    '--noreplaceqp',
    dest='replace_quoted_printable',
    required=False,
    action='store_false',
    help=
    "Replace 'Content-Type: text/quoted-printable' with text/plain (default: "
    "replace it)")
parser.add_argument(
    '--num_retries',
    default=10,
    type=int,
    help=
    'Maximum number of exponential backoff retries for failures (default: 10)')
parser.add_argument(
    '--log',
    required=False,
    default='%s-%d.log' % (APPLICATION_NAME, os.getpid()),
    help=
    'Optional: Path to a the log file (default: %s-####.log in the current '
    'directory, where #### is the process ID)' % APPLICATION_NAME)
parser.add_argument(
    '--httplib2debuglevel',
    default=0,
    type=int,
    help='Debug level of the HTTP library: 0=None (default), 4=Maximum.')
parser.add_argument(
    '--from_message',
    default=0,
    type=int,
    help=
      'Message number to resume from, affects ALL users and ALL '
      'mbox files (default: 0)')
parser.set_defaults(fix_msgid=True, replace_quoted_printable=True,
                    logging_level='INFO')
args = parser.parse_args()


def get_credentials(username):
  """Gets valid user credentials from a JSON service account key file.

  Args:
    username: The email address of the user to impersonate.
  Returns:
    Credentials, the obtained credential.
  """
  credentials = ServiceAccountCredentials.from_json_keyfile_name(
      args.json,
      scopes=SCOPES).create_delegated(username)

  return credentials


def get_label_id_from_name(service, username, labels, labelname):
  """Get label ID if it already exists, otherwise create it."""
  if labelname.endswith('.mbox'):
    # Strip .mbox suffix from folder names
    labelname = labelname[:-5]
  for label in labels:
    if label['name'].upper() == labelname.upper():
      return label['id']

  logging.info("Label '%s' doesn't exist, creating it", labelname)
  try:
    label_object = {
        'messageListVisibility': 'show',
        'name': labelname,
        'labelListVisibility': 'labelShow'
    }
    label = service.users().labels().create(
        userId=username,
        body=label_object).execute(num_retries=args.num_retries)
    logging.info("Label '%s' created", labelname)
    labels.append(label)
    return label['id']
  except Exception:
    logging.exception("Can't create label '%s' for user %s", labelname, username)
    raise


def process_mbox_files(username, service, labels):
  """Iterates over the mbox files found in the user's subdir and imports them.

  Args:
    username: The email address of the user to import into.
    service: A Gmail API service object.
    labels: Dictionary of the user's labels and their IDs.
  Returns:
    A tuple of: Number of labels imported without error,
                Number of labels imported with some errors,
                Number of labels that failed completely,
                Number of messages imported without error,
                Number of messages that failed.
  """
  number_of_labels_imported_without_error = 0
  number_of_labels_imported_with_some_errors = 0
  number_of_labels_failed = 0
  number_of_messages_imported_without_error = 0
  number_of_messages_failed = 0
  base_path = os.path.join(args.dir, username)
  for root, dirs, files in os.walk(base_path):
    for dir in dirs:
      try:
        labelname = os.path.join(root[len(base_path) + 1:], dir)
        get_label_id_from_name(service, username, labels, labelname)
      except Exception:
        logging.error("Labels under '%s' may not nest correctly", dir)
    for file in files:
      filename = root[len(base_path) + 1:]
      if filename:
        filename += u'/'
      filename += file
      labelname, ext = os.path.splitext(filename)
      full_filename = os.path.join(root, file)
      if labelname.endswith('.mbox/mbox'):
        # Assume this is an Apple Mail export, so there's an mbox file inside a
        # dir that ends with .mbox.
        labelname = labelname[:-10]
        logging.info("File '%s' looks like an Apple Mail export, importing it "
                     "into label '%s'",
                     full_filename,
                     labelname)
      elif ext != '.mbox':
        logging.info("Skipping '%s' because it doesn't have a .mbox extension",
                     full_filename)
        continue
      if os.path.isdir(full_filename):
        # This "shouldn't happen" but it does, sometimes.
        # Assume this is an Apple Mail export, so there's an mbox file inside the dir.
        full_filename += os.path.join(full_filename, 'mbox')
        logging.info("Using '%s' instead of the directory", full_filename)
      logging.info("Starting processing of '%s'", full_filename)
      number_of_successes_in_label = 0
      number_of_failures_in_label = 0
      mbox = mailbox.mbox(full_filename)
      try:
        label_id = get_label_id_from_name(service, username, labels, labelname)
      except Exception:
        logging.error("Skipping label '%s' because it can't be created", labelname)
        continue
      logging.info("Using label name '%s', ID '%s'", labelname, label_id)
      for index, message in enumerate(mbox):
        if index < args.from_message:
          continue
        logging.info("Processing message %d in label '%s'", index, labelname)
        try:
          if (args.replace_quoted_printable and
              'Content-Type' in message and
              'text/quoted-printable' in message['Content-Type']):
            message.replace_header(
                'Content-Type', message['Content-Type'].replace(
                    'text/quoted-printable', 'text/plain'))
            logging.info('Replaced text/quoted-printable with text/plain')
        except Exception:
          logging.exception(
              'Failed to replace text/quoted-printable with text/plain '
              'in Content-Type header')
        try:
          if args.fix_msgid and 'Message-ID' in message:
            msgid = message['Message-ID']
            if msgid[0] != '<':
              msgid = '<' + msgid
              logging.info('Added < to Message-ID: %s', msgid)
            if msgid[-1] != '>':
              msgid += '>'
              logging.info('Added > to Message-ID: %s', msgid)
            message.replace_header('Message-ID', msgid)
        except Exception:
          logging.exception('Failed to fix brackets in Message-ID header')
        metadata_object = {'labelIds': [label_id]}
        try:
          # Use media upload to allow messages more than 5mb.
          # See https://developers.google.com/api-client-library/python/guide/media_upload
          # and http://google-api-python-client.googlecode.com/hg/docs/epy/apiclient.http.MediaIoBaseUpload-class.html.
          if sys.version_info.major == 2:
            message_data = io.BytesIO(message.as_string())
          else:
            message_data = io.StringIO(message.as_string())
          media = MediaIoBaseUpload(message_data, mimetype='message/rfc822')
          message_response = service.users().messages().import_(
              userId=username,
              fields='id',
              neverMarkSpam=True,
              processForCalendar=False,
              internalDateSource='dateHeader',
              body=metadata_object,
              media_body=media).execute(num_retries=args.num_retries)
          number_of_successes_in_label += 1
          logging.debug("Imported mbox message '%s' to Gmail ID %s",
                        message.get_from(),
                        message_response['id'])
        except Exception:
          number_of_failures_in_label += 1
          logging.exception('Failed to import mbox message')
      logging.info("Finished processing '%s'. %d messages imported "
                   "successfully, %d messages failed.",
                   full_filename,
                   number_of_successes_in_label,
                   number_of_failures_in_label)
      if number_of_failures_in_label == 0:
        number_of_labels_imported_without_error += 1
      elif number_of_successes_in_label > 0:
        number_of_labels_imported_with_some_errors += 1
      else:
        number_of_labels_failed += 1
      number_of_messages_imported_without_error += number_of_successes_in_label
      number_of_messages_failed += number_of_failures_in_label
  return (number_of_labels_imported_without_error,     # 0
          number_of_labels_imported_with_some_errors,  # 1
          number_of_labels_failed,                     # 2
          number_of_messages_imported_without_error,   # 3
          number_of_messages_failed)                   # 4


def main():
  """Import multiple users' mbox files to Gmail.

  """
  httplib2.debuglevel = args.httplib2debuglevel
  # Use args.logging_level if defined.
  try:
    logging_level = args.logging_level
  except AttributeError:
    logging_level = 'INFO'

  # Default logging to standard output
  logging.basicConfig(
      level=logging_level,
      format='%(asctime)s %(levelname)s %(funcName)s@%(filename)s %(message)s',
      datefmt='%H:%M:%S')

  # More detailed logging to file
  file_handler = logging.handlers.RotatingFileHandler(args.log,
                                                      maxBytes=1024 * 1024 * 32,
                                                      backupCount=8)
  file_formatter = logging.Formatter(
      '%(asctime)s %(process)d %(levelname)s %(funcName)s '
      '(%(filename)s:%(lineno)d) %(message)s')
  file_formatter.datefmt = '%Y-%m-%dT%H:%M:%S (%z)'
  file_handler.setFormatter(file_formatter)
  logging.getLogger().addHandler(file_handler)

  logging.info('*** Starting %s %s on Python %s ***',
               APPLICATION_NAME,
               APPLICATION_VERSION,
               sys.version)
  logging.info('Arguments:')
  for arg, value in sorted(vars(args).items()):
    logging.info('\t%s: %r', arg, value)

  number_of_labels_imported_without_error = 0
  number_of_labels_imported_with_some_errors = 0
  number_of_labels_failed = 0
  number_of_messages_imported_without_error = 0
  number_of_messages_failed = 0
  number_of_users_imported_without_error = 0
  number_of_users_imported_with_some_errors = 0
  number_of_users_failed = 0

  for username in next(os.walk(unicode(args.dir)))[1]:
    try:
      logging.info('Processing user %s', username)
      try:
        credentials = get_credentials(username)
        http = credentials.authorize(set_user_agent(
            httplib2.Http(),
            '%s-%s' % (APPLICATION_NAME, APPLICATION_VERSION)))
        service = discovery.build('gmail', 'v1', http=http)
      except Exception:
        logging.error("Can't get access token for user %s", username)
        raise

      try:
        results = service.users().labels().list(
            userId=username,
            fields='labels(id,name)').execute(num_retries=args.num_retries)
        labels = results.get('labels', [])
      except Exception:
        logging.error("Can't get labels for user %s", username)
        raise

      try:
        result = process_mbox_files(username, service, labels)
      except Exception:
        logging.error("Can't process mbox files for user %s", username)
        raise
      if result[2] == 0 and result[4] == 0:
        number_of_users_imported_without_error += 1
      elif result[0] > 0 or result[3] > 0:
        number_of_users_imported_with_some_errors += 1
      else:
        number_of_users_failed += 1
      number_of_labels_imported_without_error += result[0]
      number_of_labels_imported_with_some_errors += result[1]
      number_of_labels_failed += result[2]
      number_of_messages_imported_without_error += result[3]
      number_of_messages_failed += result[4]
      logging.info('Done importing user %s. Labels: %d succeeded, %d with some '
                   'errors, %d failed. Messages: %d succeeded, %d failed.',
                   username,
                   result[0],
                   result[1],
                   result[2],
                   result[3],
                   result[4])
    except Exception:
      number_of_users_failed += 1
      logging.exception("Can't process user %s", username)
  logging.info("*** Done importing all users from directory '%s'", args.dir)
  logging.info('*** Import summary:')
  logging.info('    %d users imported with no failures',
               number_of_users_imported_without_error)
  logging.info('    %d users imported with some failures',
               number_of_users_imported_with_some_errors)
  logging.info('    %d users failed',
               number_of_users_failed)
  logging.info('    %d labels (mbox files) imported with no failures',
               number_of_labels_imported_without_error)
  logging.info('    %d labels (mbox files) imported with some failures',
               number_of_labels_imported_with_some_errors)
  logging.info('    %d labels (mbox files) failed',
               number_of_labels_failed)
  logging.info('    %d messages imported successfully',
               number_of_messages_imported_without_error)
  logging.info('    %d messages failed\n',
               number_of_messages_failed)
  if (number_of_messages_failed + number_of_labels_failed +
      number_of_users_failed > 0):
    logging.info('*** Check log file %s for detailed errors.', args.log)
  logging.info('Finished.\n\n')


if __name__ == '__main__':
  main()
