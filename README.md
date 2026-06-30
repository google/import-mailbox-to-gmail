# Import .mbox files to Google Workspace (formerly G Suite / Google Apps)

This script allows Google Workspace admins to import mbox files in bulk for
their users.

**DISCLAIMER**: This is not an official Google product.

If you want to migrate from Mozilla Thunderbird, try
[mail-importer](https://github.com/google/mail-importer).

You only authorize it once using a service account, and then it can import mail
into the mailboxes of all users in your domain.

## A. Creating and authorizing a service account for Gmail API

The easiest way is to
[use the automated script to authorize GWMME](https://support.google.com/a/answer/6291304#script).
The resulting JSON service account key file will work with this script as well.
It will allow more API scopes than are needed, so you might want to remove them
after it's created and verified.

If you don't want to use the automated script, you can follow the manual
instructions on the same page, but you'll only need to enable Gmail API
(not all of the other APIs), and only the two Gmail scopes:

```text
https://www.googleapis.com/auth/gmail.insert, https://www.googleapis.com/auth/gmail.labels
```

At the end of either option, you will have a JSON service account key file,
that you can use to authorize programs to access the Gmail API "insert" and
"label" scopes of all users in your Google Workspace domain.

**Remember to store this key safely, and don't share it with anyone.**

## B. Importing mbox files

**Important**: If you're planning to import mail from Apple Mail.app, see the
notes below.

You can either run the pre-compiled executable (easiest) or run the Python
script directly.

### Option 1: Using the executable (Recommended for Windows)

1. Download `import-mailbox-to-gmail.exe` from
   [the latest release](https://github.com/google/import-mailbox-to-gmail/releases/latest).
   **Note**: Executables are provided for Windows only. macOS and Linux users
   should use Option 2.

2. Open a **Command Prompt** (CMD) window.

3. Create a folder for the mbox files, for example `C:\mbox` (see step 5 below).

4. Follow steps 6-8 below, replacing `python import-mailbox-to-gmail.py` with
   the path to your downloaded executable (usually
   `%USERPROFILE%\Downloads\import-mailbox-to-gmail.exe`).

### Option 2: Running the Python script

1. Download the script `import-mailbox-to-gmail.py` from
   [the latest release](https://github.com/google/import-mailbox-to-gmail/releases/latest).

2. [Download](https://www.python.org/downloads/) and install Python 3 (latest
   version) for your operating system if needed.

3. Open a **Command Prompt** (CMD) window (on Windows) / **Terminal** window
   (on macOS/Linux).

4. Install the Google API Client Libraries for Python and their dependencies.
   Ensure you have a `requirements.txt` file (you can download it from the repo)
   in the same directory, then run:

   ```bash
   pip3 install -r requirements.txt
   ```

   **Note**: On Windows, you may need to do this on a Command Prompt window that
   was run as Administrator.

5. Create a folder for the mbox files, for example `C:\mbox` or `~/mbox`.

6. Under that folder, create a folder for each of the users into which you
   intend to import the mbox files. The folder names should be the users' full
   email addresses.

7. Into each of the folders, copy the mbox files for that user. Make sure the
   file name format is &lt;LabelName&gt;.mbox. For example, if you want the
   messages to go into a label called "Imported messages", name the file
   "Imported messages.mbox".

   Your final folder and file structure should look like this (for example):

   ```text
   C:\mbox
   C:\mbox\user1@domain.com
   C:\mbox\user1@domain.com\Imported messages.mbox
   C:\mbox\user1@domain.com\Other imported messages.mbox
   C:\mbox\user2@domain.com
   C:\mbox\user2@domain.com\Imported messages.mbox
   C:\mbox\user2@domain.com\Other imported messages.mbox
   ```

   IMPORTANT: It's essential to test the migration before migrating into the
   real users' mailboxes. First, migrate the mbox files into a test user, to
   make sure the messages are imported correctly.

8. To start the migration, run the following command (one line):

   macOS/Linux:

   ```bash
   python3 import-mailbox-to-gmail.py --json Credentials.json --dir ~/mbox
   ```

   Windows:

   ```cmd
   python import-mailbox-to-gmail.py --json Credentials.json --dir C:\mbox
   ```

   * Replace `import-mailbox-to-gmail.py` with the full path of
     import-mailbox-to-gmail.py - usually
     `~/Downloads/import-mailbox-to-gmail.py` on Mac/Linux or
     `%USERPROFILE%\Downloads\import-mailbox-to-gmail.py` on Windows.
   * Replace `Credentials.json` with the path of the JSON service account key
     file created in the previous step.
   * Replace `C:\mbox` with the path to the folder you created in step 5.

The mbox files will now be imported, one by one, into the users' mailboxes. You
can monitor the migration by looking at the output, and inspect errors by
viewing the `import-mailbox-to-gmail.log` file.

## Options and notes

* Use the `--from_message` parameter to start the upload from a particular
  message. This allows you to resume an upload if the process previously
  stopped. (Affects _all_ users and _all_ mbox files)

  e.g. `python3 import-mailbox-to-gmail.py --from_message 74336`

* By default the script imports several messages and several users at once
  (`--message_concurrency`, `--user_concurrency`, both default to 4) instead
  of doing everything one message at a time. This is controlled by the
  [Gmail API's usage quota](https://developers.google.com/workspace/gmail/api/reference/quota):
  `messages.import` costs 25 quota units, and each user has their own quota
  of 6,000 units/minute (about 4 imports/second sustained), separate from
  every other user. That means:
  * Raising `--message_concurrency` speeds up importing one very large
    mailbox, up to about 4 messages/second per user - going much higher
    mostly just adds retries rather than throughput.
  * Raising `--user_concurrency` speeds up importing many users at once,
    since each user has an independent quota bucket. This is the main lever
    for large migrations (e.g. `--user_concurrency 20`) - the project-wide
    quota (1,200,000 units/minute by default) is shared across all users,
    so the more users you run concurrently, the closer you get to using all
    of it.
  * Set either to `1` to fall back to the old one-at-a-time behavior.

* If any of the folders have a ".mbox" extension, it will be dropped when
  creating the label for it in Gmail.

* To import mail from Apple Mail.app, make sure you export it first - the raw
  Apple Mail files can't be imported. You can export a folder by right clicking
  it in Apple Mail and choosing "Export Mailbox".

* This script can import nested folders. In order to do so, it is necessary to
  preserve the email folders' hierarchy when exporting them as mbox files. In
  Apple Mail.app, this can be done by expanding all subfolders, selecting both
  parents and subfolders at the same time, and exporting them by right clicking
  the selection and choosing "Export Mailbox".

* If any of the folders have a ".mbox" extension and a file named "mbox" in
  them, the contents of the "mbox" file will be imported to the label named as
  the folder. This is how Apple Mail exports are structured.

* To run under [Docker](https://www.docker.com/):
  1. Build the image:

     ```bash
     docker build -t import-mailbox-to-gmail https://github.com/google/import-mailbox-to-gmail.git
     ```

  2. Run the import command:

     ```bash
     docker run --rm -it \
         -v "/local/path/to/auth.json:/auth.json" \
         -v "/local/path/to/mbox:/mbox" \
         import-mailbox-to-gmail --json "/auth.json" --dir "/mbox"
     ```

     **Note** `-v` is mounting a local file/directory _/local/path/to/auth.json_
     in the container as `/auth.json`. The command is then using it within the
     container `--json "/auth.json"`. For more help, see
     [Volume in Docker Run](https://docs.docker.com/engine/reference/commandline/run/#mount-volume--v---read-only).
