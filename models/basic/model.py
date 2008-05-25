# -*- coding: utf-8 -*-

# Copyright (C) 2008 Mathieu Blondel
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import ghmm
import glob

import lib.base as base

class Model(base.ModelBase):
    """
    Title: basic
    HMM: whole character
    Feature vectors: (dx, dy)
    Number of states: 3 per stroke
    Initialization: vectors distributed equally among states
    State transitions: 0.5 itself, 0.5 next state
    """

    def __init__(self, *args):
        base.ModelBase.__init__(self, *args)

        self.SAMPLING = 0.5
        self.N_STATES_PER_STROKE = 3
        self.N_DIMENSIONS = 2

        self.ROOT = os.path.join("models", "basic")
        self.update_folder_paths()

    def update_folder_paths(self):
        
        self.FEATURES_ROOT = os.path.join(self.ROOT, "features")
        self.TRAIN_FEATURES_ROOT = os.path.join(self.FEATURES_ROOT, "train")
        self.EVAL_FEATURES_ROOT = os.path.join(self.FEATURES_ROOT, "eval")

        self.INIT_HMM_ROOT = os.path.join(self.ROOT, "hmms", "init")
        self.TRAIN_HMM_ROOT = os.path.join(self.ROOT, "hmms", "train")

    ########################################
    # Feature extraction...
    ########################################

    def get_feature_vectors(self, tomoe_writing):
        """
        Get dx and dy as feature vectors.
        """
        arr = []
        
        strokes = tomoe_writing.get_strokes()

        last_x, last_y = 0, 0

        i = 0

        sampling = int(1 / self.SAMPLING)

        for stroke in strokes:
            for x,y in stroke:

                if i % sampling == 0:
                    if i != 0: # skip the very first value
                        dx = abs(x - last_x)
                        dy = abs(y - last_y)
                        arr.append([float(dx), float(dy)])

                    last_x, last_y = x, y

                i += 1

        return arr    

    def fextract(self):
        for dirname, xml_files_dict in (("eval", self.eval_xml_files_dict),
                                       ("train", self.train_xml_files_dict)):
            
            for char_code, xml_list in xml_files_dict.items():
                output_dir = os.path.join(self.FEATURES_ROOT, dirname)

                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)

                sequence_set = []

                for xml_file in xml_list:
                    tomoe_char = self.get_tomoe_char(xml_file)

                    tomoe_writing = tomoe_char.get_writing()

                    char_features = self.get_feature_vectors(tomoe_writing)

                    sequence_set.append(base.array_flatten(char_features))

                output_file = os.path.join(output_dir,
                                           str(char_code) + ".sset")


                if os.path.exists(output_file):
                    # necessary because SequenceSet#write appends content
                    os.unlink(output_file)

                sset = ghmm.SequenceSet(self.DOMAIN, sequence_set)
                sset.write(output_file)

    ########################################
    # Initialization...
    ########################################

    def get_train_feature_files(self):
        return glob.glob(os.path.join(self.TRAIN_FEATURES_ROOT, "*.sset"))

    def get_n_strokes(self, char_code):
        file = self.train_xml_files_dict[char_code][0]
        tomoe_char = self.get_tomoe_char(file)
        return tomoe_char.get_writing().get_n_strokes()

    def get_initial_state_probability(self, n_states):
        pi = [0.0] * n_states
        pi[0] = 1.0
        return pi

    def get_state_transition_matrix(self, n_states):
        matrix = []
        
        for i in range(n_states):
            # set all transitions to 0
            state = [0.0] * n_states
            
            if i == n_states - 1:
                # when the last state is reached,
                # the probability to stay in the state is 1
                state[n_states - 1] = 1.0
            else:
                # else, as an initial value, we set the prob to stay in
                # the same state to 0.5 and to jump to the next state to 0.5
                # the values will be updated by the training
                state[i] = 0.5
                state[i + 1] = 0.5

            matrix.append(state)
       
        return matrix

    def get_emission_matrix(self, n_states, sset):
        
        # contains observations for states
        # one index = one state
        dx_arr = []
        dy_arr = []

        for i in range(n_states):
            dx_arr.append([])
            dy_arr.append([])

        # go through the sequence set in order to populate dx_arr and dy_arr
        for seq in sset:
            # files contain data sequentially
            # need to reconvert to vectors of two elements
            vectors = base.array_reshape(list(seq), 2)

            # distribute vectors equally among states
            distr_vectors = base.array_split(vectors, n_states)

            for state_num in range(n_states):
                v = distr_vectors[state_num]
                for dx, dy in v:
                    dx_arr[state_num].append(dx)
                    dy_arr[state_num].append(dy)

        # calculate means and variances
        dx_means = [base.array_mean(arr) for arr in dx_arr]
        dy_means = [base.array_mean(arr) for arr in dy_arr]

        dx_variances = [base.array_variance(arr) for arr in dx_arr]
        dy_variances = [base.array_variance(arr) for arr in dy_arr]

        matrix = []

        for i in range(n_states):
            matrix.append([
                # the means of our multivariate gaussian
                [dx_means[i], dy_means[i]],
                # the covariance matrix of our multivariate gaussian
                # 1) we consider dx and dy independent for now
                # X and Y indep => COV(X,Y) = 0
                # so non-diagonal values are 0
                # 2) COV(X,X) = VAR(X)
                # so diaogonal-values are simply variances
                [dx_variances[i], 0.0, 0.0, dy_variances[i]]
                
            ])

        return matrix

    def get_initial_hmm(self, sset_file):
        char_code = int(os.path.basename(sset_file[:-5]))

        n_states = self.get_n_strokes(char_code) * \
                    self.N_STATES_PER_STROKE

        sset = self.get_sequence_set(sset_file)

        pi = self.get_initial_state_probability(n_states)
        A = self.get_state_transition_matrix(n_states)
        B = self.get_emission_matrix(n_states, sset)

        hmm = ghmm.HMMFromMatrices(
                    self.DOMAIN,
                    ghmm.MultivariateGaussianDistribution(self.DOMAIN),
                    A,
                    B,
                    pi)
        
        return hmm
          

    def init(self):
        feature_files = self.get_train_feature_files()

        if len(feature_files) == 0:
            raise base.ModelException, "No feature files found."
        
        if not os.path.exists(self.INIT_HMM_ROOT):
            os.makedirs(self.INIT_HMM_ROOT)

        for sset_file in feature_files:
            char_code = int(os.path.basename(sset_file[:-5]))

            hmm = self.get_initial_hmm(sset_file)

            output_file = os.path.join(self.INIT_HMM_ROOT,
                                       "%d.xml" % char_code)

            if os.path.exists(output_file):
                os.unlink(output_file)

            hmm.write(output_file)

    ########################################
    # Training...
    ########################################
    
    def get_initial_hmm_files(self):
        return glob.glob(os.path.join(self.INIT_HMM_ROOT, "*.xml"))

    def train(self):
        initial_hmm_files = self.get_initial_hmm_files()

        if len(initial_hmm_files) == 0:
            raise base.ModelException, "No initial HMM files found."
        
        if not os.path.exists(self.TRAIN_HMM_ROOT):
            os.makedirs(self.TRAIN_HMM_ROOT)
        
        for file in initial_hmm_files:
            char_code = int(os.path.basename(file)[:5])
            hmm = ghmm.HMMOpen(file)
            sset_file = os.path.join(self.TRAIN_FEATURES_ROOT,
                                     str(char_code) + ".sset")

            sset = self.get_sequence_set(sset_file)

            hmm.baumWelch(sset)

            output_file = os.path.join(self.TRAIN_HMM_ROOT,
                                       "%d.xml" % char_code)

            if self.verbose:
                base.stderr_print(output_file)

            if os.path.exists(output_file):
                os.unlink(output_file)

            hmm.write(output_file)

    ########################################
    # Evaluation...
    ########################################    

    def get_eval_feature_files(self):
        return glob.glob(os.path.join(self.EVAL_FEATURES_ROOT, "*.sset"))

    def get_trained_hmm_files(self):
        return glob.glob(os.path.join(self.TRAIN_HMM_ROOT, "*.xml"))

    def eval_sequence(self, seq, hmms):
        res = []
        
        for hmm in hmms:
            logp = hmm.viterbi(seq)[1]
            res.append([hmm.char_code, logp])

        if seq.__class__.__name__ == ghmm.SequenceSet:
            res.sort(key=lambda x:base.array_mean(x[1]), reverse=True)
        else:
            res.sort(key=lambda x:x[1], reverse=True)

        return res

    def get_hmms_from_files(self, files):
        hmms = []
        
        for file in files:
            char_code = int(os.path.basename(file)[:5])
            hmm = ghmm.HMMOpen(file)
            hmm.char_code = char_code     
            hmms.append(hmm)
            
        return hmms

    def evaluation(self):   
        trained_hmm_files = self.get_trained_hmm_files()

        if len(trained_hmm_files) == 0:
            raise base.ModelException, "No trained HMM files found."

        hmms = self.get_hmms_from_files(trained_hmm_files)
        
        n_total = 0
        n_match1 = 0
        n_match5 = 0
        n_match10 = 0

        s = ""
        
        for file in self.get_eval_feature_files():
            char_code = int(os.path.basename(file)[:5])
            sset = self.get_sequence_set(file)

            # evaluate all evaluation sets at the same time
            res = [x[0] for x in self.eval_sequence(sset, hmms)][:10]

            if char_code in res:
                n_match10 += 1
                matches = ", ".join([self.get_utf8_from_char_code(x) \
                                        for x in res[:10]])
            else:
                matches = "X"

            utf8 = self.get_utf8_from_char_code(char_code)

            s += "%s: %s\n" % (utf8, matches)

            if char_code in res[:5]:
                n_match5 += 1

            if char_code == res[0]:
                n_match1 += 1

            n_total += 1

        base.stderr_print("match1: ",
                          float(n_match1)/float(n_total) * 100,
                          "%")
        base.stderr_print("match5: ",
                          float(n_match5)/float(n_total) * 100,
                          "%")
        base.stderr_print("match10: ",
                          float(n_match10)/float(n_total) * 100,
                          "%")
        
        if self.verbose:
            base.stderr_print(s)

    ########################################
    # Writing pad...
    ########################################

    def find_writing(self, tomoe_writing):
        char_features = self.get_feature_vectors(tomoe_writing)
        
        seq = ghmm.EmissionSequence(self.DOMAIN,
                                    base.array_flatten(char_features))
        trained_hmm_files = self.get_trained_hmm_files()
        hmms = self.get_hmms_from_files(trained_hmm_files)
        res = [x[0] for x in self.eval_sequence(seq, hmms)][:10]
        return [self.get_utf8_from_char_code(x) for x in res]
        

    def writing_pad(self):
        from lib.writing_pad import WritingPad
        
        trained_hmm_files = self.get_trained_hmm_files()

        if len(trained_hmm_files) == 0:
            raise base.ModelException, "No trained HMM files found."
        
        pad = WritingPad(self.find_writing)
        pad.run()
        