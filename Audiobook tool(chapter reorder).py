import os
import re

# Specify the folder path
directory = r"C:\Users\Solan\OneDrive - Clark University\Clark\Personal Projects\Audiobook Tools\Warbreaker"

# List all files in the directory
filenames = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]



word_to_number = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10,
    "Eleven": 11, "Twelve": 12, "Thirteen": 13, "Fourteen": 14, "Fifteen": 15, "Sixteen": 16, "Seventeen": 17,
    "Eighteen": 18, "Nineteen": 19, "Twenty": 20, "Thirty": 30, "Forty": 40, "Fifty": 50, "Sixty": 60, "Seventy": 70,
    "Eighty": 80, "Ninety": 90, "Hundred": 100
}

def __main__():
    
    counter = 1
    print("script running")
    for filename in os.listdir(directory):
        if filename.endswith(".mp3"):  # Assuming text files, change extension as needed
            # Get the number for the filename
            number = get_word_to_number(filename, counter)
            counter += 1
            
            # Create a new filename with the number at the start
            new_filename = f"{number}-{filename}"
            
            # Get full paths
            old_file = os.path.join(directory, filename)
            new_file = os.path.join(directory, new_filename)
            
            # Rename the file
            os.rename(old_file, new_file)
            print(f"Renamed: {old_file} -> {new_file}")
    

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
                
                
    return total



if __name__ == "__main__":
    __main__()