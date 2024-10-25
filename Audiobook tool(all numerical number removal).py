import os
import re

# Specify the folder path
directory = r"E:\Libby FIles\Patrick Rothfuss\The Kingkiller Chronicles\[01] The Name of the Wind"

# List all files in the directory
filenames = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

# Function to strip numbers and hyphens until a letter is detected
def strip_until_letter(filename):
    # Remove leading numbers and hyphens until a letter is found
    match = re.search(r'[A-Za-z]', filename)
    if match:
        # Get the position of the first letter
        first_letter_index = match.start()
        # Return the filename starting from the first letter onward
        new_filename = filename[first_letter_index:]
    else:
        # If no letter is found, return the original filename (unlikely)
        new_filename = filename
    
    # Remove any extra spaces that may exist
    new_filename = new_filename.strip()
    
    return new_filename

# Iterate through files in the directory and rename them
for filename in filenames:
    # Strip numbers and hyphens until a letter is detected
    new_filename = strip_until_letter(filename)
    
    # Get full paths
    old_file = os.path.join(directory, filename)
    new_file = os.path.join(directory, new_filename)
    
    # Rename the file
    os.rename(old_file, new_file)
    print(f"Renamed: {old_file} -> {new_file}")
    
import os

# Specify the folder path


# Iterate through the files in the directory
for filename in os.listdir(directory):
    # Check if the filename ends with ".mp"
    if filename.endswith(".mp"):
        # Construct the new filename by replacing ".mp" with ".mp3"
        new_filename = filename[:-3] + ".mp3"
        
        # Get the full paths
        old_file = os.path.join(directory, filename)
        new_file = os.path.join(directory, new_filename)
        
        # Rename the file
        os.rename(old_file, new_file)
        print(f"Renamed: {old_file} -> {new_file}")

