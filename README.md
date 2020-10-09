# Import .mbox files to Google Workspace (formerly G Suite / Google Apps)

This script allows Google Workspace admins to import mbox files in bulk for their
users.

**DISCLAIMER**: This is not an official Google product.

If you want to migrate from Mozilla Thunderbird, try
[mail-importer](https://github.com/google/mail-importer).

You only authorize it once using a service account, and then it can import mail
into the mailboxes of all users in your domain.

### A. Creating and authorizing a service account for Gmail API

1. Go to the [Developers Console](https://console.developers.google.com/project)
   and log in as a domain super administrator.

2. Create a new project.

 * If you have not used the API console before, select **Create a project** from
   the **Select a project** dropdown list.
 * If this is not your first project, use the **Create Project** button.

3. Enter "Gmail API" (or any name you prefer) as the project name and press the
   **Create** button. If this is your first project you must agree to the Terms of
   Service at this point.

4. Click the **Enable and manage APIs** link in the **Use Google APIs** box. 

5. Enable the Gmail API - Select the **Gmail API** link and press the **Enable
   API** button. You can leave the default APIs enabled - it doesn't matter.

6. Click the 3-line icon (**≡**) in the top left corner of the console.

7. Click **IAM & Admin** and select **Service accounts**.

8. Click **Create service account**.

9. Enter a name (for example, "import-mailbox") in the **Name** field.

10. Check the **Furnish a new private key** box and ensure the key type is set
    to JSON.

11. Check the **Enable G Suite Domain-wide Delegation** box and enter a name
    in the **Product name for the consent screen** field.

12. Click **Create**. You will see a confirmation message advising that the
    Service account JSON file has been downloaded to your computer. Make a note
    of the location and name of this file. **This JSON file contains a private
    key that potentially allows access to all users in your domain. Protect it
    like you'd protect your admin password. Don't share it with anyone.**

13. Click **Close**.

14. Click the **View Client ID** link in the **Options** column.

15. Copy the **Client ID** value. You will need this later.

16. Go to [the **Domain-wide Delegation** page of the Admin console for your
    Google Workspace domain](https://admin.google.com/ac/owl/domainwidedelegation).

17. Under **Client ID**, enter the Client ID collected in step 15.

18. Under **OAuth Scopes**, enter the following:
   ```
   https://www.googleapis.com/auth/gmail.insert, https://www.googleapis.com/auth/gmail.labels
   ```
19. Click **Authorize**.

You can now use the JSON file to authorize programs to access the Gmail API
"insert" and "label" scopes of all users in your Google Workspace domain.

### B. Importing mbox files using import-mailbox-to-gmail.py

**Important**: If you're planning to import mail from Apple Mail.app, see the notes below.

1. Download the script - [import-mailbox-to-gmail.py](https://github.com/google/import-mailbox-to-gmail/releases/download/v1.5/import-mailbox-to-gmail.py).

2. [Download](https://www.python.org/downloads/) and install Python 2.7 (not
   Python 3.x) for your operating system if needed.

3. Open a **Command Prompt** (CMD) window (on Windows) / **Terminal** window
   (on Linux).

4. Install the Google API Client Libraries for Python and their dependencies by
   running, all in one line:

   Mac/Linux:
   ```
   sudo pip install --upgrade google-api-python-client PyOpenSSL
   ```

   Windows:
   ```
   C:\Python27\Scripts\pip install --upgrade google-api-python-client PyOpenSSL
   ```

   **Note**: On Windows, you may need to do this on a Command Prompt window that
   was run as Administrator.

5. Create a folder for the mbox files, for example `C:\mbox`.

6. Under that folder, create a folder for each of the users into which you
   intend to import the mbox files. The folder names should be the users' full
   email addresses.

7. Into each of the folders, copy the mbox files for that user. Make sure the
   file name format is &lt;LabelName&gt;.mbox. For example, if you want the
   messages to go into a label called "Imported messages", name the file
   "Imported messages.mbox".

  Your final folder and file structure should look like this (for example):
  ```
  C:\mbox
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

8. To start the migration, run the following command (one line):

   Mac/Linux:
   ```
   python import-mailbox-to-gmail.py --json Credentials.json --dir C:\mbox
   ```

   Windows:
   ```
   C:\Python27\python import-mailbox-to-gmail.py --json Credentials.json --dir C:\mbox
   ```

  * Replace `import-mailbox-to-gmail.py` with the full path of import-mailbox-to-gmail.py -
    usually `~/Downloads/import-mailbox-to-gmail.py` on Mac/Linux or
    `%USERPROFILE%\Downloads\import-mailbox-to-gmail.py` on Windows.
  * Replace `Credentials.json` with the path to the JSON file from step 12
    above.
  * Replace `C:\mbox` with the path to the folder you created in step 5.

The mbox files will now be imported, one by one, into the users' mailboxes. You
can monitor the migration by looking at the output, and inspect errors by
viewing the `import-mailbox-to-gmail.log` file.

### Options and notes

* Use the `--from_message` parameter to start the upload from a particular message.
  This allows you to resume an upload if the process previously stopped. (Affects
  _all_ users and _all_ mbox files)

  e.g. `./import-mailbox-to-gmail.py --from_message 74336`
* If any of the folders have a ".mbox" extension, it will be dropped when creating the label for it in Gmail.
* To import mail from Apple Mail.app, make sure you export it first - the raw Apple Mail files can't be imported. You can export a folder by right clicking it in Apple Mail and choosing "Export Mailbox".
* This script can import nested folders. In order to do so, it is necessary to preserve the email folders' hierarchy when exporting them as mbox files. In Apple Mail.app, this can be done by expanding all subfolders, selecting both parents and subfolders at the same time, and exporting them by right clicking the selection and choosing "Export Mailbox". 
* If any of the folders have a ".mbox" extension and a file named "mbox" in them, the contents of the "mbox" file will be imported to the label named as the folder. This is how Apple Mail exports are structured.
* To run under [Docker](https://www.docker.com/):
   1. Build the image:
	```
	docker build -t google/import-mailbox-to-gmail .
	```	
   2. Run the import command:
	```
	docker run --rm -it \
	    -v "/local/path/to/auth.json:/auth.json" \
	    -v "/local/path/to/mbox:/mbox" \
	    google/import-mailbox-to-gmail --json "/auth.json" --dir "/mbox"
	```

	**Note** `-v` is mounting a local file/directory */local/path/to/auth.json* in the container as `/auth.json`. The command is then using it within the container `--json "/auth.json"`. For more help, see [Volume in Docker Run](https://docs.docker.com/engine/reference/commandline/run/#mount-volume--v---read-only).
