#Most of this file is copied form https://github.com/abisee/pointer-generator/blob/master/batcher.py

import Queue
import time
from random import shuffle
from threading import Thread

import numpy as np
import tensorflow as tf

import config
import data

import random
random.seed(1234)


class Example(object):

  def __init__(self, content, query, summary, vocab):
    # Get ids of special tokens
    start_decoding = vocab.word2id(data.START_DECODING)
    stop_decoding = vocab.word2id(data.STOP_DECODING)

    # Process the article
    content_words = content.split()
    query_words = query.split()
    summary_words = summary.split()
    if len(content_words) > config.max_enc_steps:
      content_words = content_words[:config.max_enc_steps]
    self.enc_len = len(content_words) # store the length after truncation but before padding
    self.enc_input = [vocab.word2id(w) for w in content_words] # list of word ids; OOVs are represented by the id for UNK token
    self.query_enc_input = [vocab.word2id(w) for w in query_words]
    # Process the abstract
    
    
    summary_ids = [vocab.word2id(w) for w in summary_words] # list of word ids; OOVs are represented by the id for UNK token

    # Get the decoder input sequence and target sequence
    self.dec_input, self.target = self.get_dec_inp_targ_seqs(summary_ids, config.max_dec_steps, start_decoding, stop_decoding)
    self.dec_len = len(self.dec_input)

    # If using pointer-generator mode, we need to store some extra info
    if config.pointer_gen:
      # Store a version of the enc_input where in-article OOVs are represented by their temporary OOV id; also store the in-article OOVs words themselves
      self.enc_input_extend_vocab, self.content_oovs = data.article2ids(content_words, vocab)

      # Get a verison of the reference summary where in-article OOVs are represented by their temporary article OOV id
      abs_ids_extend_vocab = data.abstract2ids(summary_words, vocab, self.content_oovs)

      # Overwrite decoder target sequence so it uses the temp article OOV ids
      _, self.target = self.get_dec_inp_targ_seqs(abs_ids_extend_vocab, config.max_dec_steps, start_decoding, stop_decoding)

    # Store the original strings
    self.original_content = content
    self.original_query = query
    self.original_summary = summary
    


  def get_dec_inp_targ_seqs(self, sequence, max_len, start_id, stop_id):
    inp = [start_id] + sequence[:]
    target = sequence[:]
    if len(inp) > max_len: # truncate
      inp = inp[:max_len]
      target = target[:max_len] # no end_token
    else: # no truncation
      target.append(stop_id) # end token
    assert len(inp) == len(target)
    return inp, target


  def pad_decoder_inp_targ(self, max_len, pad_id):
    while len(self.dec_input) < max_len:
      self.dec_input.append(pad_id)
    while len(self.target) < max_len:
      self.target.append(pad_id)


  def pad_encoder_input(self, max_len, pad_id):
    while len(self.enc_input) < max_len:
      self.enc_input.append(pad_id)
    if config.pointer_gen:
      while len(self.enc_input_extend_vocab) < max_len:
        self.enc_input_extend_vocab.append(pad_id)


class Batch(object):
  def __init__(self, example_list, vocab, batch_size):
    self.batch_size = batch_size
    self.pad_id = vocab.word2id(data.PAD_TOKEN) # id of the PAD token used to pad sequences
    self.init_encoder_seq(example_list) # initialize the input to the encoder
    self.init_decoder_seq(example_list) # initialize the input and targets for the decoder
    self.store_orig_strings(example_list) # store the original strings


  def init_encoder_seq(self, example_list):
    # Determine the maximum length of the encoder input sequence in this batch
    max_enc_seq_len = max([ex.enc_len for ex in example_list])

    # Pad the encoder input sequences up to the length of the longest sequence
    for ex in example_list:
      ex.pad_encoder_input(max_enc_seq_len, self.pad_id)

    # Initialize the numpy arrays
    # Note: our enc_batch can have different length (second dimension) for each batch because we use dynamic_rnn for the encoder.
    self.enc_batch = np.zeros((self.batch_size, max_enc_seq_len), dtype=np.int32)
    self.enc_lens = np.zeros((self.batch_size), dtype=np.int32)
    self.enc_padding_mask = np.zeros((self.batch_size, max_enc_seq_len), dtype=np.float32)

    # Fill in the numpy arrays
    for i, ex in enumerate(example_list):
      self.enc_batch[i, :] = ex.enc_input[:]
      self.enc_lens[i] = ex.enc_len
      for j in xrange(ex.enc_len):
        self.enc_padding_mask[i][j] = 1

      self.query_enc_batch[i, :] = ex.query_enc_input[:]
      self.query_enc_lens[i] = ex.query_enc_len
      for j in xrange(ex.query_enc_len):
        self.query_enc_padding_mask[i][j] = 1


    # For pointer-generator mode, need to store some extra info
    if config.pointer_gen:
      # Determine the max number of in-article OOVs in this batch
      self.max_con_oovs = max([len(ex.content_oovs) for ex in example_list])
      # Store the in-article OOVs themselves
      self.con_oovs = [ex.content_oovs for ex in example_list]
      # Store the version of the enc_batch that uses the article OOV ids
      self.enc_batch_extend_vocab = np.zeros((self.batch_size, max_enc_seq_len), dtype=np.int32)
      for i, ex in enumerate(example_list):
        self.enc_batch_extend_vocab[i, :] = ex.enc_input_extend_vocab[:]

  def init_decoder_seq(self, example_list):
    # Pad the inputs and targets
    for ex in example_list:
      ex.pad_decoder_inp_targ(config.max_dec_steps, self.pad_id)

    # Initialize the numpy arrays.
    self.dec_batch = np.zeros((self.batch_size, config.max_dec_steps), dtype=np.int32)
    self.target_batch = np.zeros((self.batch_size, config.max_dec_steps), dtype=np.int32)
    self.dec_padding_mask = np.zeros((self.batch_size, config.max_dec_steps), dtype=np.float32)
    self.dec_lens = np.zeros((self.batch_size), dtype=np.int32)

    # Fill in the numpy arrays
    for i, ex in enumerate(example_list):
      self.dec_batch[i, :] = ex.dec_input[:]
      self.target_batch[i, :] = ex.target[:]
      self.dec_lens[i] = ex.dec_len
      for j in xrange(ex.dec_len):
        self.dec_padding_mask[i][j] = 1

  def store_orig_strings(self, example_list):
    self.original_content = [ex.original_content for ex in example_list] # list of lists
    self.original_query = [ex.original_query for ex in example_list] # list of lists
    self.original_summary = [ex.original_summary for ex in example_list] # list of lists
    

class Batcher(object):
  BATCH_QUEUE_MAX = 100 # max number of batches the batch_queue can hold

  def __init__(self, data_path, vocab, mode, batch_size, single_pass, diversity=False):
    self._data_path = data_path
    self._vocab = vocab
    self._single_pass = single_pass
    self.mode = mode
    self.batch_size = batch_size
    # Initialize a queue of Batches waiting to be used, and a queue of Examples waiting to be batched
    self._batch_queue = Queue.Queue(self.BATCH_QUEUE_MAX)
    self._example_queue = Queue.Queue(self.BATCH_QUEUE_MAX * self.batch_size)

    # Different settings depending on whether we're in single_pass mode or not
    if single_pass:
      self._num_example_q_threads = 1 # just one thread, so we read through the dataset just once
      self._num_batch_q_threads = 1  # just one thread to batch examples
      self._bucketing_cache_size = 1 # only load one batch's worth of examples before bucketing; this essentially means no bucketing
      self._finished_reading = False # this will tell us when we're finished reading the dataset
    else:
      self._num_example_q_threads = 1 #16 # num threads to fill example queue
      self._num_batch_q_threads = 1 #4  # num threads to fill batch queue
      self._bucketing_cache_size = 1 #100 # how many batches-worth of examples to load into cache before bucketing

    # Start the threads that load the queues
    self._example_q_threads = []
    for _ in xrange(self._num_example_q_threads):
      self._example_q_threads.append(Thread(target=self.fill_example_queue))
      self._example_q_threads[-1].daemon = True
      self._example_q_threads[-1].start()
    self._batch_q_threads = []
    for _ in xrange(self._num_batch_q_threads):
      self._batch_q_threads.append(Thread(target=self.fill_batch_queue))
      self._batch_q_threads[-1].daemon = True
      self._batch_q_threads[-1].start()

    # Start a thread that watches the other threads and restarts them if they're dead
    if not single_pass: # We don't want a watcher in single_pass mode because the threads shouldn't run forever
      self._watch_thread = Thread(target=self.watch_threads)
      self._watch_thread.daemon = True
      self._watch_thread.start()

  def next_batch(self):
    # If the batch queue is empty, print a warning
    if self._batch_queue.qsize() == 0:
      tf.logging.warning('Bucket input queue is empty when calling next_batch. Bucket queue size: %i, Input queue size: %i', self._batch_queue.qsize(), self._example_queue.qsize())
      if self._single_pass and self._finished_reading:
        tf.logging.info("Finished reading dataset in single_pass mode.")
        return None

    batch = self._batch_queue.get() # get the next Batch
    return batch

  def fill_example_queue(self):
    input_gen = self.text_generator()

    while True:
      try:
        (content, query, summary) = input_gen.next() # read the next example from file. article and abstract are both strings.
      except StopIteration: # if there are no more examples:
        tf.logging.info("The example generator for this example queue filling thread has exhausted data.")
        if self._single_pass:
          tf.logging.info("single_pass mode is on, so we've finished reading dataset. This thread is stopping.")
          self._finished_reading = True
          break
        else:
          raise Exception("single_pass mode is off but the example generator is out of data; error.")

      content_sentence = [sent.strip() for sent in data.abstract2sents(content)] # Use the <s> and </s> tags in abstract to get a list of sentences.
      query_sentence = [sent.strip() for sent in data.abstract2sents(query)]
      summary_sentence = [sent.strip() for sent in data.abstract2sents(summary)]

      example = Example(content_sentence,query_sentence, summary_sentence, self._vocab) # Process into an Example.
      self._example_queue.put(example) # place the Example in the example queue.

  def fill_batch_queue(self):
    while True:
      if self.mode == 'decode':
        # beam search decode mode single example repeated in the batch
        ex = self._example_queue.get()
        b = [ex for _ in xrange(self.batch_size)]
        self._batch_queue.put(Batch(b, self._vocab, self.batch_size))
      else:
        # Get bucketing_cache_size-many batches of Examples into a list, then sort
        inputs = []
        for _ in xrange(self.batch_size * self._bucketing_cache_size):
          inputs.append(self._example_queue.get())
        inputs = sorted(inputs, key=lambda inp: inp.enc_len, reverse=True) # sort by length of encoder sequence

        # Group the sorted Examples into batches, optionally shuffle the batches, and place in the batch queue.
        batches = []
        for i in xrange(0, len(inputs), self.batch_size):
          batches.append(inputs[i:i + self.batch_size])
        if not self._single_pass:
          shuffle(batches)
        for b in batches:  # each b is a list of Example objects
          self._batch_queue.put(Batch(b, self._vocab, self.batch_size))

  def watch_threads(self):
    while True:
      tf.logging.info(
        'Bucket queue size: %i, Input queue size: %i',
        self._batch_queue.qsize(), self._example_queue.qsize())

      time.sleep(60)
      for idx,t in enumerate(self._example_q_threads):
        if not t.is_alive(): # if the thread is dead
          tf.logging.error('Found example queue thread dead. Restarting.')
          new_t = Thread(target=self.fill_example_queue)
          self._example_q_threads[idx] = new_t
          new_t.daemon = True
          new_t.start()
      for idx,t in enumerate(self._batch_q_threads):
        if not t.is_alive(): # if the thread is dead
          tf.logging.error('Found batch queue thread dead. Restarting.')
          new_t = Thread(target=self.fill_batch_queue)
          self._batch_q_threads[idx] = new_t
          new_t.daemon = True
          new_t.start()


  def text_generator(self, type="train"):
    while True:
      for i in range(1,11):
        content_file = open(os.path.join("data/"+str(i), type+"_content"))
        query_file = open(os.path.join("data/"+str(i), type+"_query"))
        summary_file = open(os.path.join("data/"+str(i), type+"_summary"))
        while True:
          try:
            content_text = content_file.next()
            query_text = query_file.next()
            summary_text = summary_file.next()
          except ValueError:
            tf.logging.error('Failed to get content or query or summary from files')
            continue
          except StopIteration:
            tf.logging.error('Stopped data Iteration')
            break
          
          yield (content_text, query_text, summary_text)

