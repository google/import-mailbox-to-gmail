#Import .mbox files to Google Apps for Work

This script allows Google Apps admins to import mbox files in bulk for their users.

**DISCLAIMER**: This is not an official Google product.

If you want to migrate from Mozilla Thunderbird, try [mail-importer](https://github.com/google/mail-importer).

You only authorize it once using a service account, and then it can import mail
into the mailboxes of all users in your domain.

###A. Creating and authorizing a service account for Gmail API

1. Go to the Developers Console (https://console.developers.google.com/project)
and log in as a domain super administrator.

2. Create a new project.

 * If you have not used the API console before, select "Create a project" from the Select a project dropdown list.
 * If this is not your first project, use the "Create Project" button.

3. Enter "Gmail API" (or any name you prefer) as the project name and press the
"Create" button. If this is your first project you must agree to the Terms of
Service at this point.

4. Go to "APIs & Auth" > "APIs".

5. From the "Popular APIs" page, enable the Gmail API - Select the API link and
press the "Enable API" button. You can leave the default APIs enabled - it
doesn't matter.

6. Go to "APIs & Auth" > "Credentials".

7. Click "Add credentials".

8. Click "Service account".

9. Select "JSON" and click "Create".

10. A JSON file will be downloaded. You'll need to to use the tool later. Click
"Close" to close the "New public/private key pair" dialog.

11. Click the service account email address.

12. Copy the Client ID that is now shown (a long number).

13. Go to the Manage API client access page of the Admin console for your Google
Apps domain: https://admin.google.com/AdminHome?chromeless=1#OGX:ManageOauthClients

14. Under "Client Name", enter the Client ID collected in step 12.

15. Under "One or More API Scopes", enter the following:
   ```
   https://www.googleapis.com/auth/gmail.insert, https://www.googleapis.com/auth/gmail.labels
   ```
16. Click "Authorize".

You can now use the JSON file to authorize programs to access the Gmail API "insert" and "label" scopes of all users in your Google Apps domain.

###B. Importing mbox files using import-mailbox-to-gmail.py

1. Download and install Python 2.7 (not Python 3.4) for your operating system if
needed: https://www.python.org/downloads/

2. Open a Command Prompt (CMD) window (on Windows) / Terminal window (on Linux).

3. Install the Google API Client Libraries for Python and their dependencies by running, all in one line:

   Mac/Linux:
   ```
   sudo pip install --upgrade google-api-python-client PyOpenSSL
   ```

   Windows:
   ```
   C:\Python27\Scripts\pip install --upgrade google-api-python-client PyOpenSSL
   ```

   Note: On Windows, you may need to do this on a Command Prompt window that was
run as Administrator.

4. Create a folder for the mbox files, for example "C:\mbox".

5. Under that folder, create a folder for each of the users into which you
intend to import the mbox files. The folder names should be the users' full
email addresses.

6. Into each of the folders, copy the mbox files for that user. Make sure the
file name format is &lt;LabelName&gt;.mbox. For example, if you want the messages to
go into a label called "Imported messages", name the file
"Imported messages.mbox".

Your final folder and file structure should look like this (for example):
```C:\mbox
C:\mbox\user1@domain.com
C:\mbox\user1@domain.com\Imported messages.mbox
C:\mbox\user1@domain.com\Other imported messages.mbox
C:\mbox\user2@domain.com
C:\mbox\user2@domain.com\Imported messages.mbox
C:\mbox\user2@domain.com\Other imported messages.mbox
```

IMPORTANT: It's essential to test the migration before migrating into the real
users' mailboxes. First, migrate the mbox files into a test user, to make sure
the messages are imported correctly.

To start the migration, run the following command (one line):
```
import-mbox-to-gmail.py --json Credentials.json --dir C:\mbox --replaceqp >> import-mbox-to-gmail.log 2>&1
```

Replace "Credentials.json" with the path to the JSON file from step 10 above.
Replace "C:\mbox" with the path to the folder you created in step 4.

Note: On Linux, use `./import-mailbox-to-gmail.py` instead of `import-mailbox-to-gmail.py`.

The mbox files will now be imported, one by one, into the users' mailboxes. You
can monitor the migration by viewing the import-mbox-to-gmail.log file.

