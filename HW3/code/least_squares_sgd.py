import numpy as np
import sys
import pandas as pd

import matplotlib.pyplot as plt

from classification_base import ClassificationBase
from classification_base import ModelFitExcpetion
from rbf_kernel import RBFKernel


class LeastSquaresSGD(ClassificationBase):
    """
    Multi-class classifications, with stochastic gradient descent.
    No bias
    """
    def __init__(self, X, y, eta0=None, W=None,
                 kernel=RBFKernel,
                 max_epochs=10 ** 6,  # of times passing through N pts
                 batch_size=100,
                 progress_monitoring_freq=15000,
                 delta_percent=0.01, verbose=False,
                 test_X=None, test_y=None): #
        # call the base class's methods first
        super(LeastSquaresSGD, self).__init__(X=X, y=y, W=W)

        # set up the kernel
        self.kernel = kernel(X)

        # set up attributes used for fitting
        self.max_epochs = max_epochs
        self.delta_percent = delta_percent
        self.steps = 0
        self.verbose = verbose
        if test_X is None and test_y is None:
            print("No test data was provided.")
        self.test_X = test_X
        self.test_y = test_y
        self.batch_size = batch_size
        assert progress_monitoring_freq%batch_size == 0, \
            "need to monitor at frequencies that are multiples of the " \
            "mini-batch size."
        print("Remember not to check the log loss too often.  Expensive!")
        self.progress_monitoring_freq = progress_monitoring_freq
        self.epochs = 1
        self.points_sampled = 0
        self.converged = False # Set True if converges.
        # keep track of last n sets of weights to compute \hat(w)
        self.last_n_weights = []
        self.w_hat_variance_df = pd.DataFrame()
        self.w_hat = None

        if eta0 is None:
            self.eta0 = self.find_good_learning_rate()
        else:
            self.eta0 = eta0
        self.eta = self.eta0
        # \hat{Y} is expensive to calc, so share it across functions
        self.Yhat = None

    def find_good_learning_rate(self, starting_eta0=1e-3,
                                max_divergence_streak_length=3):
        """
        Follow Sham's advice of cranking up learning rate until the model
        diverges, then cutting it back down 50%.

        The final learning rate that is found via Sham's advice is dependent
        on how much you crank up the learning rate each time, and
        how you define divergence.

        My tool defines divergence by having a string of sequential
        diverging update steps.
        """
        eta0 = starting_eta0
        change_factor = 5

        # passed will become False once the learning rate is cranked up
        # enough to cause a model fit exception.
        passed = True
        while passed is True:
            try:
                # increase eta0 until we see divergence
                eta0 = eta0*change_factor
                print('testing eta0 = {}'.format(eta0))
                # Test high learning rates until the model diverges.
                model = self.copy()
                # reset weights (can't assert!)
                model.W = np.zeros(model.W.shape)
                model.progress_monitoring_freq = model.N
                model.eta0 = eta0
                model.eta = eta0
                model.max_epochs = 51 # make sure it fails pretty fast.
                model.run(
                    max_divergence_streak_length=max_divergence_streak_length)
                if model.epochs < model.max_epochs and \
                                model.epochs == model.max_epochs:
                    passed = False
                # If that passed without exception, passed = True
            except:
                passed = False
        assert eta0 != starting_eta0, "\n eta0 didn't change; start lower"
        print("Exploration for good eta0 started at {}; stopped passing when "
              "eta0  grew to {}".format(starting_eta0, eta0))
        # return an eta almost as high as the biggest one one that
        # didn't cause divergence
        # todo: he says dividing by 2 works.  I'm getting bouncy w/o.
        self.eta0 = eta0/change_factor
        return self.eta0

    def apply_weights(self, X):
        """
        Calculate the prediction matrix: Y_hat = XW.  No bias.
        """
        return X.dot(self.get_weights())

    def step(self, X, Y):
        """
        Update the weights and bias
        """
        n, d = X.shape  # n and d of the sub-sample of X
        assert n == Y.shape[0]
        # TODO: be positive I use W for all the points so far.

        # TODO: apply kernel, or before the step.  Then assert it's right dim
        gradient = -(1./n)*X.T.dot(Y - X.dot(self.W))
        assert gradient.shape == (self.d, self.C)

        # TODO: do I scale eta by N still?
        # TODO: subtract the gradient for grad descent (?)
        assert self.eta is not None
        self.W += -(self.eta/n)*gradient
        assert self.W.shape == (self.d ,self.C), \
            "shape of W is {}".format(self.W.shape)
        self.steps += 1

    def calc_Yhat(self, X, chunk_size=10):
        """
        Produce an (NxC) array of classes predictions.
        """
        if X.shape[0] < chunk_size:
            chunk_size = X.shape[0]
        N = X.shape[0]
        n = 0

        # for each chunk of X, transform to kernel and find Yhat.
        while n < N:
            X_chunk = X[n: n+chunk_size, ]
            kernel_chunk = self.kernel.transform(X_chunk)
            assert kernel_chunk.shape == (X_chunk.shape[0], self.kernel.d)
            Yhat_chunk = kernel_chunk.dot(self.W)
            if Yhat_chunk.shape[1] != self.C:
                import pdb; pdb.set_trace()
            if n == 0: # first pass through
                Yhat = Yhat_chunk
            else:
                Yhat = np.vstack((Yhat, Yhat_chunk))
            n += X_chunk.shape[0]

        assert Yhat.shape == (N, self.C)
        return Yhat

    def predict(self):
        """
        Predict for the entire X matrix.  We only calc 0/1 loss on whole set.
        :return:
        """
        assert self.Yhat is not None, \
            "Compute Yhat before calling predict, but don't compute too often!"
        classes = np.argmax(self.Yhat, axis=1)
        return classes

    def square_loss(self):
        # TODO: make sure I'm sharing Yhat results so I don't loop through twice.
        # TODO: make sure I'm happy passing in un-kerneled X here
        assert self.Yhat is not None, \
            "Compute Yhat before calling predict, but don't compute too often!"
        Yhat = self.Yhat
        errors = self.Y - Yhat
        # element-wise squaring:
        errors_squared = np.multiply(errors, errors)
        return errors_squared.sum()

    def shrink_eta(self, s, s_exp=0.5):
        # TODO: think about shrinking eta with time. :%
        self.eta = self.eta0/(s**s_exp)

    def results_row(self):
        """
        Return a dictionary that can be put into a Pandas DataFrame.

        Expensive!  Computes stuff for the (Nxd) X matrix.
        """
        # append on logistic regression-specific results
        self.Yhat = self.calc_Yhat(self.X)

        # call parent class for universal metrics
        row = super(LeastSquaresSGD, self).results_row()

        square_loss = self.square_loss()
        more_details = {
            "eta0":[self.eta0],
            "eta": [self.eta],  # learning rate
            "square loss": [self.square_loss()],
            "(square loss), training": [square_loss],
            "(square loss)/N, training": [square_loss/self.N],
            "step": [self.steps],
            "epoch": [self.epochs],
            "batch size": [self.batch_size],
            "points": [self.points_sampled]
            }
        row.update(more_details)
        self.Yhat = None  # wipe it so it can't be used incorrectly later
        return row

    def assess_model_on_test_data(self):
        """
        Note: this has nothing to do with model fitting.
        It is only for reporting and gaining intuition.
        """
        test_results = pd.DataFrame(
            self.apply_model(X=self.test_X, y=self.test_y,
                             data_name = 'testing'))
        t_columns = [c for c in test_results.columns
                     if 'test' in c or 'step' == c]
        return pd.DataFrame(test_results[t_columns])

    def calc_what(self):
        """
        \hat{w} is the average weights over the last n fittings
        """
        return np.array(self.last_n_weights).sum(axis=0)/\
               len(self.last_n_weights)

    def update_w_hat(self, weight_array, n=50):
        """
        \hat{w} is the average weights over the last n fittings

        It is built from a tuple of previous weights, stored in
        self.last_n_weights.
        """
        # Variance of new weights minus the recent average:

        if len(self.last_n_weights) >= n:
            self.last_n_weights.pop(0)
        self.last_n_weights.append(weight_array)
        self.w_hat = self.calc_what()

    def run(self, max_divergence_streak_length=10):
        num_diverged_epochs = 0
        #fast_convergence_epochs = 0

        # Step until converged
        while self.epochs < self.max_epochs and not self.converged:
            if self.verbose:
                print('Loop through all the data. {}th time'.format(self.epochs))
            # Shuffle each time we loop through the entire data set.
            X, Y = self.shuffle(self.X.copy(), self.Y.copy())
            num_pts = 0  # initial # of points seen in this pass through N pts

            # initialize the statistic for tracking variance
            # Should be zero if weights are initially zero.
            old_w_hat_variance = np.var(self.calc_what())

            # loop over ~all of the data points in little batches.
            num_pts = 0
            while num_pts < self.N :
                if self.points_sampled%self.progress_monitoring_freq == 0:
                    take_pulse = True
                else:
                    take_pulse = False

                idx_start = num_pts
                idx_stop = num_pts + self.batch_size
                X_sample = X[idx_start:idx_stop, ] # works even if you ask for too many rows.
                # apply the kernel transformation
                X_sample = self.kernel.transform(X_sample)
                Y_sample = Y[idx_start:idx_stop, ]

                self.step(X_sample, Y_sample)
                num_pts += X_sample.shape[0]  # loop-scoped count
                last_pass = num_pts == self.N # True if last loop in epoch
                self.points_sampled += X_sample.shape[0]  # every point ever

                if last_pass: # assess \hat{w} every N points
                    # update the average of recent weight vectors
                    w_hat_variance, w_hat_percent_improvement = \
                        self.w_hat_vitals(old_w_hat_variance)

                # take the more expensive pulse, using Yhat, which
                # requires kernel transformatin of all of X.
                if take_pulse:
                    self.record_vitals()
                    square_loss_norm = \
                        self.results.tail(1)['(square loss)/N, training'][0]
                if take_pulse and self.epochs > 1:
                    square_loss_percent_improvement = self.percent_change(
                        new = square_loss_norm, old = old_square_loss_norm)
                    if self.verbose:
                        print(square_loss_norm)
                    if self.test_convergence(square_loss_percent_improvement,
                                             w_hat_percent_improvement):
                        print("Loss optimized.  Old/N: {}, new/N:{}. Eta: {}"
                              "".format(old_square_loss_norm, square_loss_norm,
                                        self.eta))
                        self.converged = True
                        break
                    elif self.test_divergence(n=max_divergence_streak_length):
                        raise ModelFitExcpetion(
                            "\nSquare loss grew {} measurements in a row!"
                            "".format(max_divergence_streak_length))

                # save the current square loss for the next loop
                old_square_loss_norm = square_loss_norm

                if last_pass:
                    # record variables for next loop
                    old_w_hat_variance = w_hat_variance

            self.epochs +=1
            sys.stdout.write(".") # one dot per pass through ~ N pts
            if self.epochs == self.max_epochs:
                print('\n!!! Max epochs ({}) reached. !!!'.format(self.max_epochs))

            # shrink learning rate
            #self.shrink_eta(self.epochs - fast_convergence_epochs + 1)
            self.shrink_eta(self.epochs)

        print('final normalized training (square loss): {}'.format(square_loss_norm))
        self.results.reset_index(drop=True, inplace=True)


    def w_hat_vitals(self, old_w_hat_variance):
        self.update_w_hat(self.W, n=5)
        new_w_hat_variance = np.var(self.calc_what())

        w_hat_percent_improvement = self.percent_change(
            new=new_w_hat_variance, old=old_w_hat_variance)

        # record the improvement:
        w_hat_improvement = pd.DataFrame(
            {'epoch':[self.epochs],
             '\hat{w} % improvement': [w_hat_percent_improvement]})
        # record it in our tracker.
        self.w_hat_variance_df = pd.concat([self.w_hat_variance_df,
                                            w_hat_improvement], axis=0)

        return new_w_hat_variance, w_hat_percent_improvement

    def record_vitals(self):
        row_results = pd.DataFrame(self.results_row())

        # also find the square loss & 0/1 loss using test data.
        if (self.test_X is not None) and (self.test_y is not None):
            test_results = self.assess_model_on_test_data()
            row_results = pd.merge(row_results, test_results)

        self.results = pd.concat([self.results, row_results], axis=0)

    def test_convergence(self, square_loss_percent_improvement,
                         w_hat_percent_improvement):
        if self.percent_metrics_converged(square_loss_percent_improvement,
                                          w_hat_percent_improvement):
            # record convergence status
            self.converged = True # flag that it converged.

            return True

        else:
            return False

    def test_divergence(self, n):
        """
        Check stats from last n pulses and return True if they are ascending.
        """
        last_square_losses = \
            self.results.tail(n)['(square loss)/N, training']
        if len(last_square_losses) < n:
            return False
        # Check for monotonic increase:
        # http://stackoverflow.com/questions/4983258/python-how-to-check-list-monotonicity
        return all(x < y for x, y in
                   zip(last_square_losses, last_square_losses[1:]))

    def percent_change(self, new, old):
        # todo: move to parent class.
        return (new - old)/old*100.

    def percent_metrics_converged(self, *args):
        # check whether all of the metrics are less than delta_percent
        for metric in args:
            if abs(metric) > self.delta_percent:
                return False
        else:
            return True

    @staticmethod
    def has_increased_significantly(old, new, sig_fig=10**(-4)):
       """
       Return if new is larger than old in the `sig_fig` significant digit.
       """
       return(new > old and np.log10(1.-old/new) > -sig_fig)

    def plot_01_loss(self, filename=None):
        super(LeastSquaresSGD, self).plot_01_loss(y="training (0/1 loss)/N",
                                                  filename=filename)

    def plot_square_loss(self, filename=None, last_steps=None):
        fig = self.plot_ys(x='step', y1="(square loss)/N, training",
                           ylabel="(square loss)/N")
        if filename:
            fig.savefig(filename + '.pdf')

    def plot_test_and_train_square_loss_during_fitting(
            self, filename=None, colors=['#756bb1', '#2ca25f']):

        train_y = "(square loss)/N, training"
        test_y = "(square loss)/N, testing"

        fig = super(LeastSquaresSGD, self).plot_ys(
            x='step', y1=train_y, y2=test_y,
            ylabel="normalized square loss",
            logx=False, colors=colors)
        if filename is not None:
            fig.savefig(filename + '.pdf')
        return fig

    def plot_test_and_train_01_loss_during_fitting(
            self, filename=None, colors=['#756bb1', '#2ca25f']):
        train_y = "training (0/1 loss)/N"
        test_y = "testing (0/1 loss)/N"

        fig = super(LeastSquaresSGD, self).plot_ys(
            x='step', y1=train_y, y2=test_y, ylabel="normalized 0/1 loss",
            logx=False, colors=colors)
        if filename is not None:
            fig.savefig(filename + '.pdf')

    def plot_w_hat_history(self):
        x = 'epoch'
        y1 = '\hat{w} % improvement'
        self.plot_ys(df=self.w_hat_variance_df, x=x, y1=y1, y2=None,
                     ylabel= "\hat{w} % improvement",
                     y0_line=True, logx=False, logy=False,
                     colors=None, figsize=(4, 3))

