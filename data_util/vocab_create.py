import os
import collections
def write_to_bin(url_file, out_file, makevocab=False):
  """Reads the tokenized .story files corresponding to the urls listed in the url_file and writes them to a out_file."""
  print "Making bin file for URLs listed in %s..." % url_file
  
  if makevocab:
    vocab_counter = collections.Counter()

  with open(out_file, 'wb') as writer:
    with open(url_file, 'r') as reader:
      for idx,line in enumerate(reader):
        if makevocab:
          line_tokens = line.split(' ')
          tokens = line_tokens
          tokens = [t.strip() for t in tokens] # strip
          tokens = [t for t in tokens if t!=""] # remove empty
          vocab_counter.update(tokens)

  print "Finished writing file %s\n" % out_file

  # write vocab to file
  if makevocab:
    print "Writing vocab file..."
    with open(os.path.join(os.getcwd(), "vocab"), 'w') as writer:
      for word, count in vocab_counter.most_common():
        writer.write(word + ' ' + str(count) + '\n')
    print "Finished writing vocab file"



if __name__ == '__main__':

  
  # Check the stories directories contain the correct number of .story files
  write_to_bin('../data/vocab_prelim.txt', os.path.join(os.getcwd(), "test.bin"), makevocab = True)
  #write_to_bin(all_val_urls, os.path.join(finished_files_dir, "val.bin"))
  #write_to_bin(all_train_urls, os.path.join(finished_files_dir, "train.bin"), makevocab=True)

  # Chunk the data. This splits each of train.bin, val.bin and test.bin into smaller chunks, each containing e.g. 1000 examples, and saves them in finished_files/chunks
  #chunk_all()