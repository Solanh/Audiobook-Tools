import os
import re
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Specify the folder path
directory = input("Please input the directory path: ").strip().strip('"').strip("'")


# List all files in the directory

# Verify the directory path
if not os.path.isdir(directory):
    logging.error("The provided directory path is invalid. Please check the path and try again.")
else:
    # List all files in the directory
    filenames = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    logging.info(f"Found {len(filenames)} files in the directory.")


word_to_number = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10,
    "Eleven": 11, "Twelve": 12, "Thirteen": 13, "Fourteen": 14, "Fifteen": 15, "Sixteen": 16, "Seventeen": 17,
    "Eighteen": 18, "Nineteen": 19, "Twenty": 20, "Thirty": 30, "Forty": 40, "Fifty": 50, "Sixty": 60, "Seventy": 70,
    "Eighty": 80, "Ninety": 90, "Hundred": 100, "Aknowledgements": 00, "Prologue": 0, "Epilogue": 1000, 
}

def get_word_to_number(filename):
    words = re.split(r'[-\s._]', filename)
    total = 0
    count = 0  # Keeps track of words processed for current file
    first_word = 0
    first_word_found = 0
    second_word = 0
    count = 0
    prev_number = 0
    
    indicies = []
    
    dictionary = dict(enumerate(words))
    
    # Process based on specified intervals
    for index, word in enumerate(words):
        
        if word in word_to_number:
            
            indicies.append(index)
            
            if first_word_found == 0:
                first_word = word_to_number[word]
                first_word_found += 1
                
            elif first_word_found == 1:
                second_word = word_to_number[word]
                first_word_found += 1
            
    
    for i in indicies:
        if count == 0:
            total += word_to_number[dictionary[i]]
            count += 1
            prev_number = i
        elif i - 1 == prev_number:
            total += word_to_number[dictionary[i]]
            prev_number = i
            
        
            
            

                
    if first_word == 1 and second_word == 100:
        total -= 1    
            
            
            
            
            # Process only the first word if total is 20, 30, 40, etc
        
        

    logging.debug(f"Extracted number {total} from filename: {filename}")
    return total

def __main__():
    logging.info("Starting the chapter reordering process.")
    counter = 1

    for filename in filenames:
        if filename.endswith(".mp3"):  # Assuming MP3 files, adjust extension as needed
            logging.debug(f"Found MP3 file: {filename}")
            # Get the number for the filename
           
            

            
            
            number = get_word_to_number(filename)
            
       
            
            logging.debug(f"Assigned number {number} to file: {filename}")
            counter += 1
            
            # Create a new filename with the number at the start
            new_filename = f"[{number:02d}] {filename}"
            old_file_path = os.path.join(directory, filename)
            new_file_path = os.path.join(directory, new_filename)
            
            # Rename the file
            os.rename(old_file_path, new_file_path)
            logging.info(f"Renamed file {filename} to {new_filename}")
    
    logging.info("Chapter reordering process completed.")

if __name__ == "__main__":
    __main__()
