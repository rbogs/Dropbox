# Dropbox
--------------------------
INTRODUCTION
Dropbox Application is intended to keep track of local client directory and maintain copy of that directory on allocated server.
The application is based on Python asyncio library.

Features: 
	- optimise uploads to avoid uploading to server files which already exist there
	  (including files with the same content but different names or location). 
	- uses calculated CRC of each file to determine whether files are the same / different.
		A change is required to use file size & date instead of crc to determine whether local client dir is modified.
	- file names are considered as case sensitive (Linux compatibility)
	- app execution info & errors logged into dropbox.log.

App limitations and known bugs / issues specified in /DropboxApp/test_dropbox_app.py

--------------------------
TESTING
Automated test cases implemented in /DropboxApp/test_dropbox_app.py. 
Manual test can be executed using /app_exec_script.py. 

--------------------------
HOW TO USE
--------------------------
DropboxApp/app_exec_script.py module contains client and server class which shall be instantiated correspondingly on client and server.
/app_exec_script.py provides an example of how to use Dropbox application.
	
--------------------------
REQUIREMENTS
--------------------------
Python >=3.8
No additional installs required.
