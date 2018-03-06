from asr_feature_builder import ASR_Feature_Builder
import matplotlib.pyplot as plt
import numpy as np
import os
import scipy.io.wavfile as wavfile

class EM:

    def __init__(self):

        # Feature builder
        self.__feature_window_duration = 0.025 # seconds
        self.__feature_skip_duration = 0.01 # seconds
        self.__feature_nfilters = 26
        self.__feature_nfilters_keep = 13
        self.__feature_radius = 2
        self.__feature_builder = ASR_Feature_Builder()

        # Continuous builder
        self.__speech_segments = []

    def __compute_ab_matrix(self, feature_matrix, hmm_parameters):
        mean_matrix = hmm_parameters.get_mean_matrix()
        nstates = hmm_parameters.get_nstates()
        transition_matrix = hmm_parameters.get_transition_matrix()
        variance_matrix = hmm_parameters.get_variance_matrix()

        a = np.zeros((nstates, feature_matrix.shape[1]))
        b = np.zeros(a.shape)

        a[0, 0] = 1#hmm_parameters.get_initial_state_vector()
        b[-1, -1] = 1

        for t in range(1, a.shape[1]):

            a[:, t] = np.multiply( \
                np.dot( \
                    np.transpose(transition_matrix), \
                    a[:, t - 1] \
                ), \
                self.__compute_gaussian_probability(feature_matrix[:, t], mean_matrix, variance_matrix) \
            )

            b[:, -t - 1] = np.multiply(
                np.dot( \
                    transition_matrix, \
                    b[:, -t] \
                ), \
                self.__compute_gaussian_probability(feature_matrix[:, -t], mean_matrix, variance_matrix) \
            )

            a_sum = np.sum(a[:, t])
            b_sum = np.sum(b[:, -t - 1])

            if a_sum != 0:
                a[:, t] = np.true_divide(a[:, t], a_sum)
            
            if b_sum != 0:
                b[:, -t - 1] = np.true_divide(b[:, -t - 1], b_sum)

        return a, b

    def __compute_delta_percentage(self, matrix_1, matrix_2):
        matrix_sum = np.sum(np.abs(matrix_1) + np.abs(matrix_2))
        if matrix_sum == 0:
            return 0
        return np.sum(np.abs(matrix_1 - matrix_2)) / matrix_sum

    def __compute_gaussian_probability(self, feature_vector, mean_matrix, variances_matrix):
        nstates = mean_matrix.shape[1]
        feature_matrix = self.__convert_vector_to_matrix(feature_vector, nstates)
        exponent = np.multiply(-0.5, np.sum(np.true_divide(np.square(feature_matrix - mean_matrix), variances_matrix), axis = 0))
        denominator = np.multiply(np.power(2 * np.pi, nstates / 2), np.sqrt(np.prod(variances_matrix, axis = 0)))
        return np.true_divide(np.exp(exponent), denominator)

    def __compute_gz(self, a, b, feature_matrix, hmm_parameters):
        mean_matrix = hmm_parameters.get_mean_matrix()
        transition_matrix = hmm_parameters.get_transition_matrix()
        variance_matrix = hmm_parameters.get_variance_matrix()
        nstates = a.shape[0]
        nframes = a.shape[1]

        g = np.zeros(a.shape)
        z = np.zeros((nstates, nstates, nframes))

        ab = np.multiply(a[:, 0], b[:, 0])
        ab_sum = np.sum(ab)

        if ab_sum != 0:
            g[:, 0] = np.true_divide(ab, ab_sum)

        for t in range(1, nframes):
            ab = np.multiply(a[:, t], b[:, t])
            ab_sum = np.sum(ab)

            if ab_sum != 0:
                g[:, t] = np.true_divide(ab, ab_sum)

            p = self.__compute_gaussian_probability(feature_matrix[:, t], mean_matrix, variance_matrix)

            for q2 in range(0, nstates):
                for q1 in range(0, nstates):
                    z[q1, q2, t] = b[q2, t] * a[q1, t - 1] * transition_matrix[q1, q2] * p[q2]

        return g, z

    def __compute_hmm_delta_percentage(self, hmm_parameters_new, hmm_parameters_old):
        old_initial_state_vector = hmm_parameters_old.get_initial_state_vector()
        old_mean_matrix = hmm_parameters_old.get_mean_matrix()
        old_transition_matrix = hmm_parameters_old.get_transition_matrix()
        old_variance_matrix = hmm_parameters_old.get_variance_matrix()

        new_initial_state_vector = hmm_parameters_new.get_initial_state_vector()
        new_mean_matrix = hmm_parameters_new.get_mean_matrix()
        new_transition_matrix = hmm_parameters_new.get_transition_matrix()
        new_variance_matrix = hmm_parameters_new.get_variance_matrix()

        initial_state_vector_delta_percentage = self.__compute_delta_percentage(old_initial_state_vector, new_initial_state_vector)
        mean_matrix_delta_percentage = self.__compute_delta_percentage(old_mean_matrix, new_mean_matrix)
        transition_matrix_delta_percentage = self.__compute_delta_percentage(old_transition_matrix, new_transition_matrix)
        variance_matrix_delta_percentage = self.__compute_delta_percentage(old_variance_matrix, new_variance_matrix)

        return [initial_state_vector_delta_percentage, mean_matrix_delta_percentage, transition_matrix_delta_percentage, variance_matrix_delta_percentage]

    def __compute_new_hmm_parameters(self, feature_matrices, hmm_parameters):
        a_matrices = []
        b_matrices = []
        g_matrices = []
        z_matrices = []

        for feature_matrix in feature_matrices:
            a, b = self.__compute_ab_matrix(feature_matrix, hmm_parameters)
            g, z = self.__compute_gz(a, b, feature_matrix, hmm_parameters)
            a_matrices.append(a)
            b_matrices.append(b)
            g_matrices.append(g)
            z_matrices.append(z)

        self.__plot_matrices(a, b, g)
        
        new_initial_state_vector = self.__compute_new_initial_state_vector(a_matrices, b_matrices)
        new_transition_matrix = self.__compute_new_state_transition_matrix(g_matrices, z_matrices)
        new_mean_matrix = self.__compute_new_mean_matrix(feature_matrices, g_matrices)
        new_variance_matrix = self.__compute_new_variance_matrix(feature_matrices, new_mean_matrix, g_matrices)
        
        return HMM_Parameters(hmm_parameters.get_nstates(), new_initial_state_vector, new_transition_matrix, new_mean_matrix, new_variance_matrix)

    def __compute_new_initial_state_vector(self, a_matrices, b_matrices):
        nstates = a_matrices[0].shape[0]
        initial_state_vector = np.zeros(nstates)

        for i in range(0, len(a_matrices)):
            a = a_matrices[i]
            b = b_matrices[i]
            ab = np.multiply(a[:, 1], b[:, 1])
            ab_sum = np.sum(ab)
            if ab_sum != 0:
                initial_state_vector = initial_state_vector + np.true_divide(ab, ab_sum)
        
        initial_state_vector = np.true_divide(initial_state_vector, len(a_matrices))
        return np.true_divide(initial_state_vector, np.sum(initial_state_vector))

    def __compute_new_mean_matrix(self, feature_matrices, g_matrices):
        nstates = g_matrices[0].shape[0]
        nfeatures = feature_matrices[0].shape[0]
        mean_matrix = np.zeros((nfeatures, nstates), dtype = np.float)
        numerator = np.zeros(nfeatures)
        denominator = 0.0

        for q in range(0, nstates):
            for i in range(0, len(feature_matrices)):
                feature_matrix = feature_matrices[i]
                g = g_matrices[i]
                numerator = numerator + np.sum(np.multiply(feature_matrix, g[q, :]), axis = 1)
                denominator = denominator + np.sum(g[q, :])
            mean_matrix[:, q] = numerator / float(denominator)
        
        return mean_matrix

    def __compute_new_state_transition_matrix(self, g_matrices, z_matrices):
        nstates = g_matrices[0].shape[0]
        transition_matrix = np.zeros((nstates, nstates), dtype = np.float)
        numerator = np.zeros((nstates, nstates))
        denominator = np.zeros(nstates)

        for i in range(0, len(g_matrices)):
            g = g_matrices[i]
            z = z_matrices[i]
            numerator = numerator + np.sum(z[:, :, 2:], axis = 2)
            denominator = denominator + np.sum(g[:, 2:], axis = 1)
        transition_matrix = np.true_divide(numerator, denominator)
        transition_matrix = np.transpose(np.true_divide(np.transpose(transition_matrix), np.sum(transition_matrix, axis = 1)))

        return transition_matrix

    def __compute_new_variance_matrix(self, feature_matrices, new_mean_matrix, g_matrices):
        nstates = g_matrices[0].shape[0]
        nfeatures = feature_matrices[0].shape[0]
        variance_matrix = np.zeros((nfeatures, nstates), dtype = np.float)
        numerator = np.zeros(nfeatures)
        denominator = 0.0

        for q in range(0, nstates):
            for i in range(0, len(feature_matrices)):
                feature_matrix = feature_matrices[i]
                g = g_matrices[i]
                numerator = numerator + np.sum( \
                    np.multiply( \
                        np.square( \
                            feature_matrix - new_mean_matrix[:, q].reshape((nfeatures, 1)) \
                        ), \
                        g[q, :] \
                    ), \
                    axis = 1 \
                )
                denominator = denominator + np.sum(g[q, :])
            variance_matrix[:, q] = numerator / float(denominator)
        
        return variance_matrix

    def __convert_vector_to_matrix(self, vector, ncolumns):
        return np.transpose(np.tile(vector, (ncolumns, 1)))

    def __initialize_hmm_parameters(self, nstates, feature_matrices):
        nfeatures = feature_matrices[0].shape[0]
        initial_state_vector = np.zeros(nstates, dtype = np.float)
        variance_vector = np.zeros(nfeatures, dtype = np.float)
        mean_vector = np.zeros(nfeatures, dtype = np.float)
        transition_matrix = np.zeros((nstates, nstates), dtype = np.float)

        for feature_matrix in feature_matrices:
            variance_vector = np.add(variance_vector, np.square(np.std(feature_matrix, axis = 1)))
            mean_vector = np.add(mean_vector, np.mean(feature_matrix, axis = 1))    

        variance_vector = np.true_divide(variance_vector, len(feature_matrices))
        mean_vector = np.true_divide(mean_vector, len(feature_matrices))

        variance_matrix = self.__convert_vector_to_matrix(variance_vector, nstates)
        mean_matrix = self.__convert_vector_to_matrix(mean_vector, nstates)

        mean_noise_matrix = np.random.rand(nfeatures, nstates)
        variance_noise_matrix = np.random.rand(nfeatures, nstates)

        for i in range(0, nfeatures):
            mean_scale = np.std(mean_vector) / 8.0
            variance_scale = np.std(variance_vector) / 8.0
            mean_noise_matrix[i, :] = mean_scale * mean_noise_matrix[i, :]
            variance_noise_matrix[i, :] = variance_scale * variance_noise_matrix[i, :]

        #mean_matrix = np.add(mean_matrix, mean_noise_matrix)
        #variance_matrix = np.add(variance_matrix, variance_noise_matrix)

        for i in range(0, nstates - 1):
            stay_probability = 0.5
            transition_probability = 1 - stay_probability
            transition_matrix[i, i] = transition_probability
            transition_matrix[i, i + 1] = 1 - transition_probability

        # At the end the probability of staying is 100% since it is the end of the HMM
        transition_matrix[-1, -1] = 1 

        for i in range(0, nstates):
            initial_state_vector[i] = np.power(0.5, (i + 1) ** 2)     
        initial_state_vector[0] = initial_state_vector[0] + (1 - np.sum(initial_state_vector))

        return HMM_Parameters(nstates, initial_state_vector, transition_matrix, mean_matrix, variance_matrix)

    def __plot_matrices(self, a, b, g):
        fig, axes = plt.subplots(3, 1)

        axes[0].set_title("Alpha matrix")
        axes[0].xaxis.grid(True)
        axes[0].yaxis.grid(True)
        axes[0].set_xlabel("frames")
        axes[0].set_ylabel("states")
        axes[0].imshow(a, aspect='auto')

        axes[1].set_title("Beta matrix")
        axes[1].xaxis.grid(True)
        axes[1].yaxis.grid(True)
        axes[1].set_xlabel("frames")
        axes[1].set_ylabel("states")
        axes[1].imshow(b, aspect='auto')

        axes[2].set_title("Gamma matrix")
        axes[2].xaxis.grid(True)
        axes[2].yaxis.grid(True)
        axes[2].set_xlabel("frames")
        axes[2].set_ylabel("states")
        axes[2].imshow(g, aspect='auto')

        fig.tight_layout(pad = 0)
        plt.show()

    def build_hmm_from_folder(self, folder_path, nstates):
        audio_files = []

        for file in os.listdir(folder_path):
            if file.endswith(".wav"):
                file_path = os.path.join(folder_path, file)
                audio_files.append(file_path)
        
        return self.build_hmm_from_files(audio_files, nstates)

    def build_hmm_from_files(self, audio_files, nstates):
        signals = []
        fs = -1

        for audio_file in audio_files:
            fs, s = wavfile.read(audio_file, 'rb')
            signals.append(s)
        
        return self.build_hmm_from_signals(signals, fs, nstates)

    def build_hmm_from_feature_matrices(self, feature_matrices, nstates):
        threshold = 0.05
        delta = 1.0
        old_hmm_parameters = self.__initialize_hmm_parameters(nstates, feature_matrices)
        new_hmm_parameters = None

        #animation = animation.FuncAnimation(self.__fig, self.__update_plots, interval = self.__data_update_interval * 1000, blit = True)
        while delta > threshold:
            new_hmm_parameters = self.__compute_new_hmm_parameters(feature_matrices, old_hmm_parameters)
            delta = np.max(self.__compute_hmm_delta_percentage(new_hmm_parameters, old_hmm_parameters))
            old_hmm_parameters = new_hmm_parameters

        return new_hmm_parameters

    def build_hmm_from_signals(self, signals, fs, nstates):
        feature_matrices = []

        for s in signals:
            feature_matrix = self.__feature_builder.compute_features_for_signal( \
                s, \
                fs, \
                self.__feature_nfilters, \
                self.__feature_window_duration, \
                self.__feature_skip_duration, \
                self.__feature_radius, \
                self.__feature_nfilters_keep)

            feature_matrices.append(feature_matrix)
        
        return self.build_hmm_from_feature_matrices(feature_matrices, nstates)

    def build_hmm_continuous(self, speech_segment, fs, nstates):
        self.__speech_segments.append(speech_segment)

        return self.build_hmm_from_signals(self.__speech_segments, fs, nstates)

class HMM_Parameters:

    def __init__(self, nstates, initial_state_vector, transition_matrix, mean_matrix, variance_matrix):
        self.__initial_state_vector = initial_state_vector
        self.__mean_matrix = mean_matrix
        self.__nstates = nstates
        self.__transition_matrix = transition_matrix
        self.__variance_matrix = variance_matrix

    def get_initial_state_vector(self):
        return self.__initial_state_vector

    def get_mean_matrix(self):
        return self.__mean_matrix

    def get_nstates(self):
        return self.__nstates
    
    def get_transition_matrix(self):
        return self.__transition_matrix

    def get_variance_matrix(self):
        return self.__variance_matrix

if __name__ == '__main__':
    folder_path = "C:\Users\AkramAsylum\OneDrive\Courses\School\EE 516 - Compute Speech Processing\Assignments\Assignment 5\samples\odessa"

    em = EM()
    em.build_hmm_from_folder(folder_path,10)