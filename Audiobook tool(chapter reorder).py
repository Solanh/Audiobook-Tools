import os
import re
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Specify the folder path
directory = r"C:\Users\Solan\OneDrive - Clark University\Clark\Personal Projects\Audiobook Tools\Warbreaker"

# List all files in the directory
filenames = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
logging.info(f"Found {len(filenames)} files in the directory.")

word_to_number = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10,
    "Eleven": 11, "Twelve": 12, "Thirteen": 13, "Fourteen": 14, "Fifteen": 15, "Sixteen": 16, "Seventeen": 17,
    "Eighteen": 18, "Nineteen": 19, "Twenty": 20, "Thirty": 30, "Forty": 40, "Fifty": 50, "Sixty": 60, "Seventy": 70,
    "Eighty": 80, "Ninety": 90, "Hundred": 100
}

def get_word_to_number(filename, counter):
    words = re.split(r'[-\s.]', filename)
    total = 0
    other_counter = 0
    
    while counter < len(filenames):
        for word in words:
            if word in word_to_number and counter % 10 == 0:
                total += word_to_number[word]
                
            elif word in word_to_number and other_counter < 2:
                total += word_to_number[word]
                other_counter += 1
                
    logging.debug(f"Processing file: {filename}")    
    return total
    
    

def __main__():
    logging.info("Starting the chapter reordering process.")
    
    counter = 1
    
    for filename in os.listdir(directory):
        if filename.endswith(".mp3"):  # Assuming text files, change extension as needed
            logging.debug(f"Found MP3 file: {filename}")
            # Get the number for the filename
            number = get_word_to_number(filename, counter)
            logging.debug(f"Assigned number {number} to file: {filename}")
            counter += 1
            
            # Create a new filename with the number at the start
            new_filename = f"{number:02d}_{filename}"
            old_file_path = os.path.join(directory, filename)
            new_file_path = os.path.join(directory, new_filename)
            
            # Rename the file
            os.rename(old_file_path, new_file_path)
            logging.info(f"Renamed file {filename} to {new_filename}")
    
    logging.info("Chapter reordering process completed.")

if __name__ == "__main__":
    __main__()