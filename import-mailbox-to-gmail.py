#!/usr/bin/env python3
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
import concurrent.futures
import io
import itertools
import logging
import logging.handlers
import mailbox
import os
import sys
import threading

import httplib2
import google.auth
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient import discovery
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.http import set_user_agent

APPLICATION_NAME = 'import-mailbox-to-gmail'
APPLICATION_VERSION = '2.0'

SCOPES = ['https://www.googleapis.com/auth/gmail.insert',
          'https://www.googleapis.com/auth/gmail.labels']


parser = argparse.ArgumentParser(
    description='Import mbox files to a specified label for many users.',
    formatter_class=argparse.RawDescriptionHelpFormatter,
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
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
    '--json',
    help='Path to the JSON key file from https://console.developers.google.com')
group.add_argument(
    '--service_account_email',
    help='The email address of the service account to use for signing JWTs')
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
    '--message_concurrency',
    default=4,
    type=int,
    help=
    'Number of messages to import concurrently per mbox file (default: 4). '
    "The Gmail API's default quota for messages.import is 25 units per call "
    'and 6,000 units/minute per user, i.e. about 4 imports/second sustained '
    "per user, so pushing this much higher than that mostly just adds "
    'retries rather than throughput.')
parser.add_argument(
    '--user_concurrency',
    default=4,
    type=int,
    help=
    'Number of users to import concurrently (default: 4). Each user draws '
    'from their own per-user quota, so raising this scales throughput '
    'across many users, up to the project-wide quota (default 1,200,000 '
    'units/minute).')
parser.add_argument(
    '--log',
    required=False,
    default=f'{APPLICATION_NAME}-{os.getpid()}.log',
    help=
    f'Optional: Path to a the log file (default: {APPLICATION_NAME}-####.log in the current '
    'directory, where #### is the process ID)')
parser.add_argument(
    '--from_message',
    default=0,
    type=int,
    help=
      'Message number to resume from, affects ALL users and ALL '
      'mbox files (default: 0)')
parser.add_argument(
    '--httplib2debuglevel',
    default=0,
    type=int,
    help='Debug level of the HTTP library: 0=None (default), 4=Maximum.')
parser.set_defaults(fix_msgid=True, replace_quoted_printable=True,
                    logging_level='INFO')
ARGS = None

# httplib2.Http (and services built on it) isn't safe to share across
# threads, so each worker thread gets its own. Credentials themselves are
# safe to share and are reused to avoid re-authenticating per thread.
_thread_local_service = threading.local()


def get_service_for_thread(credentials):
  """Returns a Gmail API service object local to the current thread."""
  if not hasattr(_thread_local_service, 'service'):
    http = set_user_agent(
        httplib2.Http(), f'{APPLICATION_NAME}-{APPLICATION_VERSION}')
    authed_http = AuthorizedHttp(credentials, http=http)
    _thread_local_service.service = discovery.build(
        'gmail', 'v1', http=authed_http, cache_discovery=False) # pylint: disable=no-member
  return _thread_local_service.service


def imap_bounded(executor, fn, items, max_in_flight):
  """Applies fn to items via executor, yielding results as they complete.

  At most max_in_flight futures are in flight at once, so memory use
  doesn't grow with the size of a (potentially huge) mbox file.
  """
  iterator = iter(items)
  in_flight = {
      executor.submit(fn, item): item
      for item in itertools.islice(iterator, max_in_flight)
  }
  while in_flight:
    done, _ = concurrent.futures.wait(
        in_flight, return_when=concurrent.futures.FIRST_COMPLETED)
    for future in done:
      del in_flight[future]
      yield future.result()
    for item in itertools.islice(iterator, len(done)):
      in_flight[executor.submit(fn, item)] = item


def get_credentials(username):
  """Gets valid user credentials from a JSON service account key file.

  Args:
    username: The email address of the user to impersonate.
  Returns:
    Credentials, the obtained credential.
  """
  if ARGS.json:
    credentials = service_account.Credentials.from_service_account_file(
        ARGS.json,
        scopes=SCOPES,
        subject=username)
  else:
    # Use Application Default Credentials to sign a JWT
    source_credentials, _ = google.auth.default(scopes=SCOPES)
    credentials = google.auth.impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=ARGS.service_account_email,
        target_scopes=SCOPES,
        subject=username)

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
        body=label_object).execute(num_retries=ARGS.num_retries)
    logging.info("Label '%s' created", labelname)
    labels.append(label)
    return label['id']
  except Exception: # pylint: disable=broad-exception-caught
    logging.exception("Can't create label '%s' for user %s", labelname, username)
    raise


def import_message(service, username, message, label_id):
  """Imports a single message to Gmail."""
  metadata_object = {'labelIds': [label_id]}
  try:
    # Use media upload to allow messages more than 5mb.
    # See https://developers.google.com/api-client-library/python/guide/media_upload
    # and http://google-api-python-client.googlecode.com/hg/docs/epy/
    # apiclient.http.MediaIoBaseUpload-class.html.
    message_data = io.BytesIO(message.as_string().encode('utf-8'))
    media = MediaIoBaseUpload(message_data, mimetype='message/rfc822')
    message_response = service.users().messages().import_(
        userId=username,
        fields='id',
        neverMarkSpam=True,
        processForCalendar=False,
        internalDateSource='dateHeader',
        body=metadata_object,
        media_body=media).execute(num_retries=ARGS.num_retries)
    logging.debug("Imported mbox message '%s' to Gmail ID %s",
                  message.get_from(),
                  message_response['id'])
    return True
  except Exception: # pylint: disable=broad-exception-caught
    logging.exception('Failed to import mbox message')
    return False


def process_message_headers(message):
  """Fixes message headers."""
  try:
    if (ARGS.replace_quoted_printable and
        'Content-Type' in message and
        'text/quoted-printable' in message['Content-Type']):
      message.replace_header(
          'Content-Type', message['Content-Type'].replace(
              'text/quoted-printable', 'text/plain'))
      logging.info('Replaced text/quoted-printable with text/plain')
  except Exception: # pylint: disable=broad-exception-caught
    logging.exception(
        'Failed to replace text/quoted-printable with text/plain '
        'in Content-Type header')

  try:
    if ARGS.fix_msgid and 'Message-ID' in message:
      msgid = message['Message-ID']
      if msgid[0] != '<':
        msgid = '<' + msgid
        logging.info('Added < to Message-ID: %s', msgid)
      if msgid[-1] != '>':
        msgid += '>'
        logging.info('Added > to Message-ID: %s', msgid)
      message.replace_header('Message-ID', msgid)
  except Exception: # pylint: disable=broad-exception-caught
    logging.exception('Failed to fix brackets in Message-ID header')


def process_mbox_file(full_filename, labelname, service, username, labels,
                       credentials=None):
  """Imports all messages from a single mbox file.

  If credentials is given and --message_concurrency > 1, messages are
  imported concurrently using a per-thread service built from credentials
  (see get_service_for_thread). Otherwise, messages are imported
  sequentially using the given service, exactly as before.
  """
  try:
    label_id = get_label_id_from_name(service, username, labels, labelname)
  except Exception: # pylint: disable=broad-exception-caught
    logging.error("Skipping label '%s' because it can't be created", labelname)
    return None

  logging.info("Using label name '%s', ID '%s'", labelname, label_id)

  number_of_successes_in_label = 0
  number_of_failures_in_label = 0

  def import_one(item):
    index, message = item
    logging.info("Processing message %d in label '%s'", index, labelname)
    process_message_headers(message)
    worker_service = (
        get_service_for_thread(credentials) if credentials is not None
        else service)
    return import_message(worker_service, username, message, label_id)

  mbox = mailbox.mbox(full_filename)
  try:
    items = ((index, message) for index, message in enumerate(mbox)
              if index >= ARGS.from_message)

    if credentials is not None and ARGS.message_concurrency > 1:
      with concurrent.futures.ThreadPoolExecutor(
          max_workers=ARGS.message_concurrency) as executor:
        results = imap_bounded(
            executor, import_one, items, ARGS.message_concurrency * 2)
        for success in results:
          if success:
            number_of_successes_in_label += 1
          else:
            number_of_failures_in_label += 1
    else:
      for item in items:
        if import_one(item):
          number_of_successes_in_label += 1
        else:
          number_of_failures_in_label += 1
  finally:
    mbox.close()

  logging.info("Finished processing '%s'. %d messages imported "
               "successfully, %d messages failed.",
               full_filename,
               number_of_successes_in_label,
               number_of_failures_in_label)

  return number_of_successes_in_label, number_of_failures_in_label


def process_mbox_files(username, service, labels, credentials=None): # pylint: disable=too-many-locals
  """Iterates over the mbox files found in the user's subdir and imports them.

  Args:
    username: The email address of the user to import into.
    service: A Gmail API service object.
    labels: Dictionary of the user's labels and their IDs.
    credentials: Credentials used to build per-thread services when
      --message_concurrency > 1. If None, messages are imported
      sequentially using service.
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
  base_path = os.path.join(ARGS.dir, username)
  for root, dirs, files in os.walk(base_path):
    for dirname in dirs:
      try:
        labelname = os.path.join(root[len(base_path) + 1:], dirname)
        get_label_id_from_name(service, username, labels, labelname)
      except Exception: # pylint: disable=broad-exception-caught
        logging.error("Labels under '%s' may not nest correctly", dirname)
    for file in files:
      filename = root[len(base_path) + 1:]
      if filename:
        filename += '/'
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

      result = process_mbox_file(
          full_filename, labelname, service, username, labels, credentials)

      if result is None:
        number_of_labels_failed += 1
        continue

      successes, failures = result

      if failures == 0:
        number_of_labels_imported_without_error += 1
      elif successes > 0:
        number_of_labels_imported_with_some_errors += 1
      else:
        number_of_labels_failed += 1
      number_of_messages_imported_without_error += successes
      number_of_messages_failed += failures
  return (number_of_labels_imported_without_error,     # 0
          number_of_labels_imported_with_some_errors,  # 1
          number_of_labels_failed,                     # 2
          number_of_messages_imported_without_error,   # 3
          number_of_messages_failed)                   # 4


def setup_logging():
  """Configures logging."""
  httplib2.debuglevel = ARGS.httplib2debuglevel
  # Use ARGS.logging_level if defined.
  logging_level = getattr(ARGS, 'logging_level', 'INFO')

  # Default logging to standard output
  logging.basicConfig(
      level=logging_level,
      format='%(asctime)s %(levelname)s %(funcName)s@%(filename)s %(message)s',
      datefmt='%H:%M:%S')

  # More detailed logging to file
  file_handler = logging.handlers.RotatingFileHandler(ARGS.log,
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
  for arg, value in sorted(vars(ARGS).items()):
    logging.info('\t%s: %r', arg, value)


def process_user(username):
  """Imports for a single user. Returns stats tuple."""
  try:
    logging.info('Processing user %s', username)
    try:
      credentials = get_credentials(username)
      http = set_user_agent(
          httplib2.Http(),
          f'{APPLICATION_NAME}-{APPLICATION_VERSION}')
      authed_http = AuthorizedHttp(credentials, http=http)
      service = discovery.build('gmail', 'v1', http=authed_http,
                                cache_discovery=False) # pylint: disable=no-member
    except Exception: # pylint: disable=broad-exception-caught
      logging.error("Can't get access token for user %s", username)
      raise

    try:
      # pylint: disable=no-member
      results = service.users().labels().list(
          userId=username,
          fields='labels(id,name)').execute(num_retries=ARGS.num_retries)
      labels = results.get('labels', [])
    except Exception: # pylint: disable=broad-exception-caught
      logging.error("Can't get labels for user %s", username)
      raise

    try:
      result = process_mbox_files(username, service, labels, credentials)
    except Exception: # pylint: disable=broad-exception-caught
      logging.error("Can't process mbox files for user %s", username)
      raise

    return result

  except Exception: # pylint: disable=broad-exception-caught
    logging.exception("Can't process user %s", username)
    return None


def main(argv): # pylint: disable=too-many-locals
  """Import multiple users' mbox files to Gmail.

  """
  global ARGS # pylint: disable=global-statement
  ARGS = parser.parse_args(argv)

  setup_logging()

  number_of_labels_imported_without_error = 0
  number_of_labels_imported_with_some_errors = 0
  number_of_labels_failed = 0
  number_of_messages_imported_without_error = 0
  number_of_messages_failed = 0
  number_of_users_imported_without_error = 0
  number_of_users_imported_with_some_errors = 0
  number_of_users_failed = 0

  usernames = next(os.walk(ARGS.dir))[1]
  with concurrent.futures.ThreadPoolExecutor(
      max_workers=ARGS.user_concurrency) as executor:
    future_to_username = {
        executor.submit(process_user, username): username
        for username in usernames
    }
    for future in concurrent.futures.as_completed(future_to_username):
      username = future_to_username[future]
      result = future.result()
      if result:
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
      else:
        number_of_users_failed += 1

  logging.info("*** Done importing all users from directory '%s'", ARGS.dir)
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
    logging.info('*** Check log file %s for detailed errors.', ARGS.log)
  logging.info('Finished.\n\n')


if __name__ == '__main__':
  main(sys.argv[1:])
