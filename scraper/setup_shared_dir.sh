#!/bin/bash

echo "This script will help set up a shared directory and permissions for your scraper project."
echo "You will likely need to run this script with sudo, e.g., sudo bash this_script_name.sh"
echo "If you don't run the script with sudo initially, individual commands might fail."
echo "------------------------------------------------------------------------------------"

# Get inputs from the user
read -p "Enter the desired absolute path for the shared directory (e.g., /opt/scraper_data/json_files): " SHARED_DIR
read -p "Enter the username that runs your PHP scripts (e.g., www-data, apache, nginx): " PHP_USER
read -p "Enter the username that runs your Python scraper scripts (e.g., your own login username): " PYTHON_USER
read -p "Enter a name for the new common group (e.g., scrapergroup, projectname_users): " COMMON_GROUP

echo "------------------------------------------------------------------------------------"
echo "You have entered the following values:"
echo "Shared Directory Path: $SHARED_DIR"
echo "PHP Process User:      $PHP_USER"
echo "Python Script User:    $PYTHON_USER"
echo "Common Group Name:     $COMMON_GROUP"
echo "------------------------------------------------------------------------------------"
read -p "Is this information correct? (yes/no): " CONFIRMATION

if [[ "$CONFIRMATION" != "yes" ]]; then
    echo "Aborted by user."
    exit 1
fi

echo ""
echo "Attempting to perform setup steps. Ensure you are running this script with sudo if errors occur."
echo ""

# --- 1. Group Creation ---
if grep -q "^$COMMON_GROUP:" /etc/group; then
    echo "INFO: Group '$COMMON_GROUP' already exists."
else
    echo "STEP: Creating group '$COMMON_GROUP'..."
    groupadd "$COMMON_GROUP"
    if [ $? -eq 0 ]; then
        echo "SUCCESS: Group '$COMMON_GROUP' created."
    else
        echo "ERROR: Failed to create group '$COMMON_GROUP'. This usually requires sudo privileges."
        echo "Exiting. Please re-run the script with 'sudo bash your_script_name.sh'"
        exit 1
    fi
fi

# --- 2. Add PHP User to Group ---
echo "STEP: Adding user '$PHP_USER' to group '$COMMON_GROUP'..."
usermod -a -G "$COMMON_GROUP" "$PHP_USER"
if [ $? -eq 0 ]; then
    echo "SUCCESS: User '$PHP_USER' added to group '$COMMON_GROUP'."
    echo "NOTE: Group membership changes for running services (like your web server for PHP) may require a service restart to take effect."
else
    echo "WARNING: Failed to add user '$PHP_USER' to group '$COMMON_GROUP'. Check if user exists. This usually requires sudo."
    # Don't exit here, allow user to see other steps, but it's a critical failure if user not in group.
fi

# --- 3. Add Python User to Group ---
echo "STEP: Adding user '$PYTHON_USER' to group '$COMMON_GROUP'..."
usermod -a -G "$COMMON_GROUP" "$PYTHON_USER"
if [ $? -eq 0 ]; then
    echo "SUCCESS: User '$PYTHON_USER' added to group '$COMMON_GROUP'."
    echo "NOTE: Group membership changes for '$PYTHON_USER' might require you to log out and log back in for them to take effect in your shell."
else
    echo "WARNING: Failed to add user '$PYTHON_USER' to group '$COMMON_GROUP'. Check if user exists. This usually requires sudo."
fi

# --- 4. Create Shared Directory ---
echo "STEP: Creating shared directory '$SHARED_DIR'..."
mkdir -p "$SHARED_DIR"
if [ $? -eq 0 ]; then
    echo "SUCCESS: Directory '$SHARED_DIR' created (or already existed)."
else
    echo "ERROR: Failed to create directory '$SHARED_DIR'. This may require sudo if in a protected location."
    echo "Exiting. Please re-run the script with 'sudo bash your_script_name.sh'"
    exit 1
fi

# --- 5. Set Ownership and Permissions for Shared Directory ---
# Ownership: Python user (writer) and the common group
# Permissions: Owner and Group get full rwx, Others get rx (or r if execute not needed by 'others')
echo "STEP: Setting ownership of '$SHARED_DIR' to '$PYTHON_USER:$COMMON_GROUP'..."
chown "$PYTHON_USER":"$COMMON_GROUP" "$SHARED_DIR"
if [ $? -eq 0 ]; then
    echo "SUCCESS: Ownership of '$SHARED_DIR' set to '$PYTHON_USER:$COMMON_GROUP'."
else
    echo "ERROR: Failed to set ownership on '$SHARED_DIR'. Check user/group names. This usually requires sudo."
    echo "Exiting. Please re-run the script with 'sudo bash your_script_name.sh'"
    exit 1
fi

echo "STEP: Setting permissions of '$SHARED_DIR' to 775 (rwxrwxr-x)..."
chmod 775 "$SHARED_DIR"
# This allows the Python user (owner) to rwx, anyone in the COMMON_GROUP to rwx,
# and others to read and execute (list directory contents).
if [ $? -eq 0 ]; then
    echo "SUCCESS: Permissions for '$SHARED_DIR' set to 775."
else
    echo "ERROR: Failed to set permissions on '$SHARED_DIR'. This usually requires sudo."
    echo "Exiting. Please re-run the script with 'sudo bash your_script_name.sh'"
    exit 1
fi

echo "------------------------------------------------------------------------------------"
echo "Setup attempt complete."
echo ""
echo "Please verify the setup:"
echo "1. Check group existence and membership:"
echo "   getent group $COMMON_GROUP"
echo "   (Ensure both '$PHP_USER' and '$PYTHON_USER' are listed as members)"
echo ""
echo "2. Check directory ownership and permissions:"
echo "   ls -ld \"$SHARED_DIR\""
echo "   (Should show owner as '$PYTHON_USER', group as '$COMMON_GROUP', and permissions drwxrwxr-x)"
echo ""
echo "3. Test file creation (as Python user) and readability (as PHP user if possible)."
echo "   Example test (run these commands manually in your terminal):"
echo "   sudo -u $PYTHON_USER touch \"$SHARED_DIR/test_by_python.txt\""
echo "   sudo -u $PHP_USER ls -l \"$SHARED_DIR/test_by_python.txt\""
echo "   sudo -u $PYTHON_USER rm \"$SHARED_DIR/test_by_python.txt\""
echo ""
echo "If any 'ERROR' messages appeared above, you almost certainly need to run this entire script using 'sudo bash your_script_name.sh'"
echo "------------------------------------------------------------------------------------"
