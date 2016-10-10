import numpy as np
import scipy.sparse as sp

class Lasso:
    def __init__(self, X, y, lam, w, w0=0, delta=0.01, verbose = False):
        """

        :param X: A scipy.csc matrix (sparse matrix) of features.
                  Rows are training data and columns are features.
        :param wo: initial weight to use for bias.  Not sparse.
        """
        for a in [X, w]:
            assert(type(a[0,0]) == np.float64)

        assert type(X) == sp.csc_matrix
        self.X = X
        assert type(y) == np.ndarray
        self.y = y
        self.w = w        # sp.csc_matrix
        assert w.shape == (self.X.shape[1], 1)
        self.w0 = w0*1.
        self.lam = lam
        self.delta = delta
        self.yhat = None  # sp.csc_matrix
        self.N = self.X.shape[0]
        self.verbose = verbose

    def optimize_weights(self):
        if self.verbose:
            print("begin optimizing weights")

        # have to initialize old_w before entering the while loop.
        old_w = self.w + \
                sp.csc_matrix(np.ones(self.w.shape[0])).T*2*self.delta #sparse
        # Initialize a high objective function value for the first loop.
        old_objective_fun_val = 10**100

        assert(self.is_converged(old_w) is False)

        # check that the weights haven't converged.
        while not self.is_converged(old_w):
            old_w = self.w.copy()   #sparse

            # calculate predictions to avoid numerical drift.
            # import pdb; pdb.set_trace()
            old_yhat = self.calculate_yhat()  #not sparse

            # update the bias.
            old_w0 = self.w0  # get it before we write over it
            self.update_w0(old_yhat)  # updates self.w0

            # update our predictions, yhat, using the new w0.
            self.update_yhat(old_yhat, old_w0)  # updates self.yhat

            if self.verbose:
                print("-- new round of wk updates --")
                print("old_w:")
                print(old_w.toarray())
            # iterate over the d features
            for k in range(0, self.w.shape[0]):
                # note: also updates the yhats element by element.
                self.update_wk(k)

            # check that the objective function decreased
            new_objective_fun_val = self.calc_objective_fun()

            if not self.check_for_objective_decrease(
                    old_value = old_objective_fun_val,
                    new_value = new_objective_fun_val):
                print("** Woah.  Objective would increase.  Weights:")
                print("old w:")
                print(old_w.toarray())
                print("old w0: {}".format(old_w0))
                self.print_weights()
                print("old predictions:")
                print(old_yhat)
                print("new predictions:")
                print(self.yhat)
                import pdb; pdb.set_trace()
            assert self.check_for_objective_decrease(
                    old_value = old_objective_fun_val,
                    new_value = new_objective_fun_val) is True, \
                   "objecive function would be updated from {} to {}".format(
                    old_objective_fun_val, new_objective_fun_val)

            old_objective_fun_val = new_objective_fun_val

            if self.verbose:
                print("weights for this loop:")
                print(self.w.toarray())

        if self.verbose:
            print("=== Lasso optimized. ===")
            self.print_weights()
            print("--- final predictions ---")
            yhat = self.calculate_yhat()
            print("final y predictions:")
            print(yhat)
            print("objective function value: {}".format(
                self.calc_objective_fun()))

        return

    def calculate_yhat(self):
        # multiply X*w + w_o
        # returns vector of predictions, yhat.
        if self.verbose:
            print("Calc X*w + w_0 for w =")
            print(self.w.toarray())
            print("  and w0 = {}".format(self.w0))

        # don't want to store this yhat.  Temporary.
        #yhat =self.X.dot(self.w).toarray()[:,0] + self.w0
        #assert yhat.shape == (self.N, )
        # todo: use my function for a w0 array.
        yhat = self.X.dot(self.w) +  np.ones((self.N, 1))*self.w0
        assert yhat.shape == (self.N, 1)

        if self.verbose:
            print("current yhat prediction:")
            print(yhat)

        return yhat

    def update_w0(self, old_yhat):
        new_w0 = sum(self.y - old_yhat)/self.N + self.w0
        new_w0 = self.extract_scalar(new_w0)
        assert type(new_w0*1.0) == np.float64  # sometimes I had int.
        self.w0 = new_w0

    def update_yhat(self, old_yhat, old_w0):
        self.yhat = old_yhat + self.w0 - old_w0
        assert type(self.yhat == np.array)
        assert self.yhat.shape[1] == 1

    def update_wk(self, k):
        """
        :param k: zero-indexed column
        :return:
        """
        Xik = self.X[:, k]  # array  (slice of sparse matrix)
        wk = self.extract_scalar(self.w[k])
        ak = 2*self.extract_scalar(Xik.T.dot(Xik))

        tmp = self.y - self.yhat + Xik.toarray()*wk
        assert tmp.shape[1] == 1  # column vector
        ck = 2*self.extract_scalar(Xik.T.dot(tmp))

        # apply the update rule.
        if self.verbose:
            print("ck = {} for k = {}, ak ={}, lambda: {}".format(
                ck, k, ak, self.lam))
        if ck < - self.lam:
            self.w[k] = (ck + self.lam)/ak
        elif ck > self.lam:
            if self.verbose:
                print("self.w[k]: {}".format(self.extract_scalar(self.w[k])))
                print("ck > self.lam, so update w[{}] from {}".format(
                    k, self.extract_scalar(self.w[k])))
                print( "new w[{}]: {}".format(k, (ck - self.lam)/ak))
            self.w[k] = (ck - self.lam)/ak
        else:
            self.w[k] = 0

        # update yhat.  wk is the old value and self.w[k] is the new one.
        self.yhat = self.y + Xik*(wk - self.extract_scalar(self.w[k]))
        assert self.yhat.shape == (self.N, 1)

    def calc_objective_fun(self):
        preds = self.X.dot(self.w) + self.w0_as_array()
        preds_error = preds - self.y
        preds_error_squared = \
            self.extract_scalar(preds_error.T.dot(preds_error))
        penalty = self.lam * np.linalg.norm(self.w.toarray()[:,0], 1)
        return preds_error_squared + penalty

    def is_converged(self, old_w):
        # stop when no element of w changes by more than some small delta
        # return True if it is time to stop.
        # see HW pg 8.

        if self.verbose:
            print("Testing convergence.")
            self.print_weights()

        # make a vector of the differences in each element
        delta_w = old_w - self.w

        for w_i in delta_w :
            if abs(w_i) > self.delta:
                return False

        return True

    def w0_as_array(self):
        return np.ones((self.N, 1))*self.w0

    @staticmethod
    def check_for_objective_decrease(old_value, new_value):
        if new_value - old_value < 10**(-6):
            return True
        else:
            return False

    @staticmethod
    def extract_scalar(m):
        """
        :param m: A 1x1 sparse matrix.
        :return: The entry in that matrix.
        """
        assert(m.shape == (1,1))
        return m[0,0]

    def print_weights(self):
        print("w:")
        print(self.w.toarray())
        print("w0: {}".format(self.w0))


class RegularizationPath:
    def __init__(self):
        pass

    def determine_smallest_lambda(self):
        pass
