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
import mailbox
import os

from apiclient import discovery
import httplib2
from apiclient.http import MediaIoBaseUpload
from oauth2client.client import SignedJwtAssertionCredentials

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
    help="Don't fix Message-ID headers that are missing brackets "
    "(default: fix them)")
parser.add_argument(
    '--replaceqp',
    dest='replace_quoted_printable',
    required=False,
    action='store_true',
    help=
    "Replace 'Content-Type: text/quoted-printable' with text/plain (default: "
    "don't change it)")
parser.add_argument(
    '--num_retries',
    default=10,
    type=int,
    help=
    'Maximum number of exponential backoff retries for failures (default: 10)')
parser.set_defaults(fix_msgid=True, replace_quoted_printable=False)
args = parser.parse_args()

SCOPES = ['https://www.googleapis.com/auth/gmail.insert',
          'https://www.googleapis.com/auth/gmail.labels']
APPLICATION_NAME = 'Google Apps Gmail mbox importer'


def get_credentials(username):
  """Gets valid user credentials from a JSON service account key file.

  Args:
    username: The email address of the user to impersonate.
  Returns:
    Credentials, the obtained credential.
  """
  json_file = json.load(open(args.json))
  credentials = SignedJwtAssertionCredentials(json_file['client_email'],
                                              json_file['private_key'],
                                              SCOPES,
                                              sub=username)

  return credentials


def get_label_id_from_name(service, username, labels, labelname):
  """Get label ID if it already exists, otherwise create it."""
  for label in labels:
    if label['name'] == labelname:
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
    return label['id']
  except:
    logging.exception("Can't create label '%s' for user %s", labelname,
                      username)
    raise


def main():
  """Iterates over the mbox files found in subdir and imports them into Gmail.

  """
  logging.basicConfig(
      level='INFO',
      format=('%(asctime)s %(process)d %(levelname)s %(funcName)s '
              '(%(filename)s:%(lineno)d) %(message)s'),
      datefmt='%Y-%m-%dT%H:%M:%S (%z)')
  logging.info('Arguments:')
  for arg, value in sorted(vars(args).items()):
      logging.info('\t%s: %r', arg, value)
  for username in next(os.walk(args.dir))[1]:
    try:
      logging.info('Processing user %s', username)
      try:
        credentials = get_credentials(username)
        http = credentials.authorize(httplib2.Http())
        service = discovery.build('gmail', 'v1', http=http)
      except:
        logging.exception("Can't get access token for user %s", username)
        raise

      try:
        results = service.users().labels().list(
            userId=username,
            fields='labels(id,name)').execute(num_retries=args.num_retries)
        labels = results.get('labels', [])
      except:
        logging.exception("Can't get labels for user %s", username)
        raise

      try:
        for filename in os.listdir(os.path.join(args.dir, username)):
          labelname, ext = os.path.splitext(filename)
          full_filename = os.path.join(args.dir, username, filename)
          if ext == '.mbox':
            logging.info("Starting processing of '%s'", full_filename)
            mbox = mailbox.mbox(full_filename)
            label_id = get_label_id_from_name(service, username, labels,
                                              labelname)
            logging.info("Using label name '%s', ID '%s'", labelname, label_id)
            for index, message in enumerate(mbox):
              logging.info("Processing message %d in label '%s'", index,
                           labelname)
              try:
                if (args.replace_quoted_printable and
                    'Content-Type' in message and
                    'text/quoted-printable' in message['Content-Type']):
                  message.replace_header(
                      'Content-Type', message['Content-Type'].replace(
                          'text/quoted-printable', 'text/plain'))
                  logging.info('Replaced text/quoted-printable with text/plain')
              except (KeyboardInterrupt, SystemExit):
                raise
              except:
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
              except (KeyboardInterrupt, SystemExit):
                raise
              except:
                logging.exception('Failed to fix brackets in Message-ID header')
              try:
                metadata_object = {'labelIds': [label_id]}
                # Use media upload to allow messages more than 5mb.
                # See https://developers.google.com/api-client-library/python/guide/media_upload
                # and http://google-api-python-client.googlecode.com/hg/docs/epy/apiclient.http.MediaIoBaseUpload-class.html.
                message_data = io.BytesIO(message.as_string())
                media = MediaIoBaseUpload(message_data,
                                          mimetype='message/rfc822')
                message_response = service.users().messages().import_(
                    userId=username,
                    fields='id',
                    neverMarkSpam=True,
                    processForCalendar=False,
                    internalDateSource='dateHeader',
                    body=metadata_object,
                    media_body=media).execute(num_retries=args.num_retries)
                logging.debug("Imported mbox message '%s' to Gmail ID %s",
                              message.get_from(), message_response['id'])
              except (KeyboardInterrupt, SystemExit):
                raise
              except:
                logging.exception('Failed to import mbox message')
            logging.info("Finished processing '%s'", full_filename)
          else:
            logging.info(
                "Skipping '%s' because it doesn't have a .mbox extension",
                full_filename)
      except (KeyboardInterrupt, SystemExit):
        raise
      except:
        logging.exception("Can't process mbox files for user %s", username)
        raise
      logging.info('Done importing user %s', username)
    except (KeyboardInterrupt, SystemExit):
      raise
    except:
      logging.exception("Can't process user %s", username)
  logging.info("Done importing all users from directory '%s'", args.dir)


if __name__ == '__main__':
  main()
