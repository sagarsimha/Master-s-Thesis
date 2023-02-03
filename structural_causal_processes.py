"""Tigramite toymodels."""

# Author: Jakob Runge <jakob@jakob-runge.com>
#
# License: GNU General Public License v3.0
from __future__ import print_function
from collections import defaultdict, OrderedDict
import sys
import warnings
import copy
import math
import numpy as np
import scipy.sparse
import scipy.sparse.linalg
from numba import jit
import itertools

def _generate_noise(covar_matrix, time=1000, use_inverse=False):
    """
    Generate a multivariate normal distribution using correlated innovations.

    Parameters
    ----------
    covar_matrix : array
        Covariance matrix of the random variables
    time : int
        Sample size
    use_inverse : bool, optional
        Negate the off-diagonal elements and invert the covariance matrix
        before use

    Returns
    -------
    noise : array
        Random noise generated according to covar_matrix
    """
    # Pull out the number of nodes from the shape of the covar_matrix
    n_nodes = covar_matrix.shape[0]
    # Make a deep copy for use in the inverse case
    this_covar = covar_matrix
    # Take the negative inverse if needed
    if use_inverse:
        this_covar = copy.deepcopy(covar_matrix)
        this_covar *= -1
        this_covar[np.diag_indices_from(this_covar)] *= -1
        this_covar = np.linalg.inv(this_covar)
    # Return the noise distribution
    return np.random.multivariate_normal(mean=np.zeros(n_nodes),
                                            cov=this_covar,
                                            size=time)

def _check_stability(graph):
    """
    Raises an AssertionError if the input graph corresponds to a non-stationary
    process.

    Parameters
    ----------
    graph : array
        Lagged connectivity matrices. Shape is (n_nodes, n_nodes, max_delay+1)
    """
    # Get the shape from the input graph
    n_nodes, _, period = graph.shape
    # Set the top section as the horizontally stacked matrix of
    # shape (n_nodes, n_nodes * period)
    stability_matrix = \
        scipy.sparse.hstack([scipy.sparse.lil_matrix(graph[:, :, t_slice])
                             for t_slice in range(period)])
    # Extend an identity matrix of shape
    # (n_nodes * (period - 1), n_nodes * (period - 1)) to shape
    # (n_nodes * (period - 1), n_nodes * period) and stack the top section on
    # top to make the stability matrix of shape
    # (n_nodes * period, n_nodes * period)
    stability_matrix = \
        scipy.sparse.vstack([stability_matrix,
                             scipy.sparse.eye(n_nodes * (period - 1),
                                              n_nodes * period)])
    # Check the number of dimensions to see if we can afford to use a dense
    # matrix
    n_eigs = stability_matrix.shape[0]
    if n_eigs <= 25:
        # If it is relatively low in dimensionality, use a dense array
        stability_matrix = stability_matrix.todense()
        eigen_values, _ = scipy.linalg.eig(stability_matrix)
    else:
        # If it is a large dimensionality, convert to a compressed row sorted
        # matrix, as it may be easier for the linear algebra package
        stability_matrix = stability_matrix.tocsr()
        # Get the eigen values of the stability matrix
        eigen_values = scipy.sparse.linalg.eigs(stability_matrix,
                                                k=(n_eigs - 2),
                                                return_eigenvectors=False)
    # Ensure they all have less than one magnitude
    assert np.all(np.abs(eigen_values) < 1.), \
        "Values given by time lagged connectivity matrix corresponds to a "+\
        " non-stationary process!"

def _check_initial_values(initial_values, shape):
    """
    Raises a AssertionError if the input initial values:
        * Are not a numpy array OR
        * Do not have the shape (n_nodes, max_delay+1)

    Parameters
    ----------
    graph : array
        Lagged connectivity matrices. Shape is (n_nodes, n_nodes, max_delay+1)
    """
    # Ensure it is a numpy array
    assert isinstance(initial_values, np.ndarray),\
        "User must provide initial_values as a numpy.ndarray"
    # Check the shape is correct
    assert initial_values.shape == shape,\
        "Initial values must be of shape (n_nodes, max_delay+1)"+\
        "\n current shape : " + str(initial_values.shape)+\
        "\n desired shape : " + str(shape)

def _var_network(graph,
                 add_noise=True,
                 inno_cov=None,
                 invert_inno=False,
                 T=100,
                 initial_values=None):
    """Returns a vector-autoregressive process with correlated innovations.

    Useful for testing.

    Example:
        graph=numpy.array([[[0.2,0.,0.],[0.5,0.,0.]],
                           [[0.,0.1,0. ],[0.3,0.,0.]]])

        represents a process

        X_1(t) = 0.2 X_1(t-1) + 0.5 X_2(t-1) + eps_1(t)
        X_2(t) = 0.3 X_2(t-1) + 0.1 X_1(t-2) + eps_2(t)

        with inv_inno_cov being the negative (except for diagonal) inverse
        covariance matrix of (eps_1(t), eps_2(t)) OR inno_cov being
        the covariance. Initial values can also be provided.


    Parameters
    ----------
    graph : array
        Lagged connectivity matrices. Shape is (n_nodes, n_nodes, max_delay+1)
    add_noise : bool, optional (default: True)
        Flag to add random noise or not
    inno_cov : array, optional (default: None)
        Covariance matrix of innovations.
    invert_inno : bool, optional (defualt : False)
        Flag to negate off-diagonal elements of inno_cov and invert it before
        using it as the covariance matrix of innovations
    T : int, optional (default: 100)
        Sample size.

    initial_values : array, optional (defult: None)
        Initial values for each node. Shape is (n_nodes, max_delay+1), i.e. must
        be of shape (graph.shape[1], graph.shape[2]).

    Returns
    -------
    X : array
        Array of realization.
    """
    n_nodes, _, period = graph.shape

    time = T
    # Test stability
    _check_stability(graph)

    # Generate the returned data
    data = np.random.randn(n_nodes, time)
    # Load the initial values
    if initial_values is not None:
        # Check the shape of the initial values
        _check_initial_values(initial_values, data[:, :period].shape)
        # Input the initial values
        data[:, :period] = initial_values

    # Check if we are adding noise
    noise = None
    if add_noise:
        # Use inno_cov if it was provided
        if inno_cov is not None:
            noise = _generate_noise(inno_cov,
                                    time=time,
                                    use_inverse=invert_inno)
        # Otherwise just use uncorrelated random noise
        else:
            noise = np.random.randn(time, n_nodes)

    for a_time in range(period, time):
        data_past = np.repeat(
            data[:, a_time-period:a_time][:, ::-1].reshape(1, n_nodes, period),
            n_nodes, axis=0)
        data[:, a_time] = (data_past*graph).sum(axis=2).sum(axis=1)
        if add_noise:
            data[:, a_time] += noise[a_time]

    return data.transpose()

def _iter_coeffs(parents_neighbors_coeffs):
    """
    Iterator through the current parents_neighbors_coeffs structure.  Mainly to
    save repeated code and make it easier to change this structure.

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.

    Yields
    -------
    (node_id, parent_id, time_lag, coeff) : tuple
        Tuple defining the relationship between nodes across time
    """
    # Iterate through all defined nodes
    for node_id in list(parents_neighbors_coeffs):
        # Iterate over parent nodes and unpack node and coeff
        for (parent_id, time_lag), coeff in parents_neighbors_coeffs[node_id]:
            # Yield the entry
            yield node_id, parent_id, time_lag, coeff

def _check_parent_neighbor(parents_neighbors_coeffs):
    """
    Checks to insure input parent-neighbor connectivity input is sane.  This
    means that:
        * all time lags are non-positive
        * all parent nodes are included as nodes themselves
        * all node indexing is contiguous
        * all node indexing starts from zero
    Raises a ValueError if any one of these conditions are not met.

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.
    """
    # Initialize some lists for checking later
    all_nodes = set()
    all_parents = set()
    # Iterate through variables
    for j in list(parents_neighbors_coeffs):
        # Cache all node ids to ensure they are contiguous
        all_nodes.add(j)
    # Iterate through all nodes
    for j, i, tau, _ in _iter_coeffs(parents_neighbors_coeffs):
        # Check all time lags are equal to or less than zero
        if tau > 0:
            raise ValueError("Lag between parent {} and node {}".format(i, j)+\
                             " is {} > 0, must be <= 0!".format(tau))
        # Cache all parent ids to ensure they are mentioned as node ids
        all_parents.add(i)
    # Check that all nodes are contiguous from zero
    all_nodes_list = sorted(list(all_nodes))
    if all_nodes_list != list(range(len(all_nodes_list))):
        raise ValueError("Node IDs in input dictionary must be contiguous"+\
                         " and start from zero!\n"+\
                         " Found IDs : [" +\
                         ",".join(map(str, all_nodes_list))+ "]")
    # Check that all parent nodes are mentioned as a node ID
    if not all_parents.issubset(all_nodes):
        missing_nodes = sorted(list(all_parents - all_nodes))
        all_parents_list = sorted(list(all_parents))
        raise ValueError("Parent IDs in input dictionary must also be in set"+\
                         " of node IDs."+\
                         "\n Parent IDs "+" ".join(map(str, all_parents_list))+\
                         "\n Node IDs "+" ".join(map(str, all_nodes_list)) +\
                         "\n Missing IDs " + " ".join(map(str, missing_nodes)))

def _check_symmetric_relations(a_matrix):
    """
    Check if the argument matrix is symmetric.  Raise a value error with details
    about the offending elements if it is not.  This is useful for checking the
    instantaneously linked nodes have the same link strength.

    Parameters
    ----------
    a_matrix : 2D numpy array
        Relationships between nodes at tau = 0. Indexed such that first index is
        node and second is parent, i.e. node j with parent i has strength
        a_matrix[j,i]
    """
    # Check it is symmetric
    if not np.allclose(a_matrix, a_matrix.T, rtol=1e-10, atol=1e-10):
        # Store the disagreement elements
        bad_elems = ~np.isclose(a_matrix, a_matrix.T, rtol=1e-10, atol=1e-10)
        bad_idxs = np.argwhere(bad_elems)
        error_message = ""
        for node, parent in bad_idxs:
            # Check that we haven't already printed about this pair
            if bad_elems[node, parent]:
                error_message += \
                    "Parent {:d} of node {:d}".format(parent, node)+\
                    " has coefficient {:f}.\n".format(a_matrix[node, parent])+\
                    "Parent {:d} of node {:d}".format(node, parent)+\
                    " has coefficient {:f}.\n".format(a_matrix[parent, node])
            # Check if we already printed about this one
            bad_elems[node, parent] = False
            bad_elems[parent, node] = False
        raise ValueError("Relationships between nodes at tau=0 are not"+\
                         " symmetric!\n"+error_message)

def _find_max_time_lag_and_node_id(parents_neighbors_coeffs):
    """
    Function to find the maximum time lag in the parent-neighbors-coefficients
    object, as well as the largest node ID

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.

    Returns
    -------
    (max_time_lag, max_node_id) : tuple
        Tuple of the maximum time lag and maximum node ID
    """
    # Default maximum lag and node ID
    max_time_lag = 0
    max_node_id = len(parents_neighbors_coeffs.keys()) - 1
    # Iterate through the keys in parents_neighbors_coeffs
    for j, _, tau, _ in _iter_coeffs(parents_neighbors_coeffs):
        # Find max lag time
        max_time_lag = max(max_time_lag, abs(tau))
        # Find the max node ID
        # max_node_id = max(max_node_id, j)
    # Return these values
    return max_time_lag, max_node_id

def _get_true_parent_neighbor_dict(parents_neighbors_coeffs):
    """
    Function to return the dictionary of true parent neighbor causal
    connections in time.

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.

    Returns
    -------
    true_parent_neighbor : dict
        Dictionary of lists of tuples.  The dictionary is keyed by node ID, the
        list stores the tuple values (parent_node_id, time_lag)
    """
    # Initialize the returned dictionary of lists
    true_parents_neighbors = defaultdict(list)
    for j in parents_neighbors_coeffs:
        for link_props in parents_neighbors_coeffs[j]:
            i, tau = link_props[0]
            coeff = link_props[1]
            # Add parent node id and lag if non-zero coeff
            if coeff != 0.:
                true_parents_neighbors[j].append((i, tau))
    # Return the true relations
    return true_parents_neighbors

def _get_covariance_matrix(parents_neighbors_coeffs):
    """
    Determines the covariance matrix for correlated innovations

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.

    Returns
    -------
    covar_matrix : numpy array
        Covariance matrix implied by the parents_neighbors_coeffs.  Used to
        generate correlated innovations.
    """
    # Get the total number of nodes
    _, max_node_id = \
            _find_max_time_lag_and_node_id(parents_neighbors_coeffs)
    n_nodes = max_node_id + 1
    # Initialize the covariance matrix
    covar_matrix = np.identity(n_nodes)
    # Iterate through all the node connections
    for j, i, tau, coeff in _iter_coeffs(parents_neighbors_coeffs):
        # Add to covar_matrix if node connection is instantaneous
        if tau == 0:
            covar_matrix[j, i] = coeff
    return covar_matrix

def _get_lag_connect_matrix(parents_neighbors_coeffs):
    """
    Generates the lagged connectivity matrix from a parent-neighbor
    connectivity dictionary.  Used to generate the input for _var_network

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format:
        {..., j:[((var1, lag1), coef1), ((var2, lag2), coef2), ...], ...} for
        all variables where vars must be in [0..N-1] and lags <= 0 with number
        of variables N.

    Returns
    -------
    connect_matrix : numpy array
        Lagged connectivity matrix. Shape is (n_nodes, n_nodes, max_delay+1)
    """
    # Get the total number of nodes and time lag
    max_time_lag, max_node_id = \
            _find_max_time_lag_and_node_id(parents_neighbors_coeffs)
    n_nodes = max_node_id + 1
    n_times = max_time_lag + 1
    # Initialize full time graph
    connect_matrix = np.zeros((n_nodes, n_nodes, n_times))
    for j, i, tau, coeff in _iter_coeffs(parents_neighbors_coeffs):
        # If there is a non-zero time lag, add the connection to the matrix
        if tau != 0:
            connect_matrix[j, i, -(tau+1)] = coeff
    # Return the connectivity matrix
    return connect_matrix

def var_process(parents_neighbors_coeffs, T=1000, use='inv_inno_cov',
                verbosity=0, initial_values=None):
    """Returns a vector-autoregressive process with correlated innovations.

    Wrapper around var_network with possibly more user-friendly input options.

    Parameters
    ----------
    parents_neighbors_coeffs : dict
        Dictionary of format: {..., j:[((var1, lag1), coef1), ((var2, lag2),
        coef2), ...], ...} for all variables where vars must be in [0..N-1]
        and lags <= 0 with number of variables N. If lag=0, a nonzero value
        in the covariance matrix (or its inverse) is implied. These should be
        the same for (i, j) and (j, i).
    use : str, optional (default: 'inv_inno_cov')
        Specifier, either 'inno_cov' or 'inv_inno_cov'.
        Any other specifier will result in non-correlated noise.
        For debugging, 'no_noise' can also be specified, in which case random
        noise will be disabled.
    T : int, optional (default: 1000)
        Sample size.
    verbosity : int, optional (default: 0)
        Level of verbosity.
    initial_values : array, optional (default: None)
        Initial values for each node. Shape must be (N, max_delay+1)

    Returns
    -------
    data : array-like
        Data generated from this process
    true_parent_neighbor : dict
        Dictionary of lists of tuples.  The dictionary is keyed by node ID, the
        list stores the tuple values (parent_node_id, time_lag)
    """
    # Check the input parents_neighbors_coeffs dictionary for sanity
    _check_parent_neighbor(parents_neighbors_coeffs)
    # Generate the true parent neighbors graph
    true_parents_neighbors = \
        _get_true_parent_neighbor_dict(parents_neighbors_coeffs)
    # Generate the correlated innovations
    innos = _get_covariance_matrix(parents_neighbors_coeffs)
    # Generate the lagged connectivity matrix for _var_network
    connect_matrix = _get_lag_connect_matrix(parents_neighbors_coeffs)
    # Default values as per 'inno_cov'
    add_noise = True
    invert_inno = False
    # Use the correlated innovations
    if use == 'inno_cov':
        if verbosity > 0:
            print("\nInnovation Cov =\n%s" % str(innos))
    # Use the inverted correlated innovations
    elif use == 'inv_inno_cov':
        invert_inno = True
        if verbosity > 0:
            print("\nInverse Innovation Cov =\n%s" % str(innos))
    # Do not use any noise
    elif use == 'no_noise':
        add_noise = False
        if verbosity > 0:
            print("\nInverse Innovation Cov =\n%s" % str(innos))
    # Use decorrelated noise
    else:
        innos = None
    # Ensure the innovation matrix is symmetric if it is used
    if (innos is not None) and add_noise:
        _check_symmetric_relations(innos)
    # Generate the data using _var_network
    data = _var_network(graph=connect_matrix,
                        add_noise=add_noise,
                        inno_cov=innos,
                        invert_inno=invert_inno,
                        T=T,
                        initial_values=initial_values)
    # Return the data
    return data, true_parents_neighbors

class _Graph():
    r"""Helper class to handle graph properties.

    Parameters
    ----------
    vertices : list
        List of nodes.
    """
    def __init__(self,vertices): 
        self.graph = defaultdict(list) 
        self.V = vertices 
  
    def addEdge(self,u,v):
        """Adding edge to graph."""
        self.graph[u].append(v) 
  
    def isCyclicUtil(self, v, visited, recStack): 
        """Utility function to return whether graph is cyclic."""
        # Mark current node as visited and
        # adds to recursion stack 
        visited[v] = True
        recStack[v] = True
  
        # Recur for all neighbours 
        # if any neighbour is visited and in  
        # recStack then graph is cyclic 
        for neighbour in self.graph[v]: 
            if visited[neighbour] == False: 
                if self.isCyclicUtil(neighbour, visited, recStack) == True: 
                    return True
            elif recStack[neighbour] == True: 
                return True
  
        # The node needs to be poped from  
        # recursion stack before function ends 
        recStack[v] = False
        return False
  
    def isCyclic(self):
        """Returns whether graph is cyclic."""
        visited = [False] * self.V 
        recStack = [False] * self.V 
        for node in range(self.V): 
            if visited[node] == False: 
                if self.isCyclicUtil(node,visited,recStack) == True: 
                    return True
        return False
  
    def topologicalSortUtil(self,v,visited,stack):
        """A recursive function used by topologicalSort ."""
        # Mark the current node as visited.
        visited[v] = True

        # Recur for all the vertices adjacent to this vertex
        for i in self.graph[v]:
            if visited[i] == False:
                self.topologicalSortUtil(i,visited,stack)

        # Push current vertex to stack which stores result
        stack.insert(0,v)

    def topologicalSort(self):
        """A sorting function. """
        # Mark all the vertices as not visited 
        visited = [False]*self.V 
        stack =[] 

        # Call the recursive helper function to store Topological 
        # Sort starting from all vertices one by one 
        for i in range(self.V): 
          if visited[i] == False: 
              self.topologicalSortUtil(i,visited,stack) 

        return stack

def structural_causal_process(links, T, noises=None, 
                        intervention=None, intervention_type='hard',
                        seed=None):
    """Returns a time series generated from a structural causal process.

    Allows lagged and contemporaneous dependencies and includes the option
    to have intervened variables or particular samples.

    The interventional data is in particular useful for generating ground
    truth for the CausalEffects class.

    In more detail, the method implements a generalized additive noise model process of the form

    .. math:: X^j_t = \\eta^j_t + \\sum_{X^i_{t-\\tau}\\in \\mathcal{P}(X^j_t)}
              c^i_{\\tau} f^i_{\\tau}(X^i_{t-\\tau})

    Links have the format ``{0:[((i, -tau), coeff, func),...], 1:[...],
    ...}`` where ``func`` can be an arbitrary (nonlinear) function provided
    as a python callable with one argument and coeff is the multiplication
    factor. The noise distributions of :math:`\\eta^j` can be specified in
    ``noises``.

    Through the parameters ``intervention`` and ``intervention_type`` the model
    can also be generated with intervened variables.

    Parameters
    ----------
    links : dict
        Dictionary of format: {0:[((i, -tau), coeff, func),...], 1:[...],
        ...} for all variables where i must be in [0..N-1] and tau >= 0 with
        number of variables N. coeff must be a float and func a python
        callable of one argument.
    T : int
        Sample size.
    noises : list of callables, optional (default: 'np.random.randn')
        Random distribution function that is called with noises[j](T).
    intervention : dict
        Dictionary of format: {1:np.array, ...} containing only keys of intervened
        variables with the value being the array of length T with interventional values.
        Set values to np.nan to leave specific time points of a variable un-intervened.
    intervention_type : str or dict
        Dictionary of format: {1:'hard',  3:'soft', ...} to specify whether intervention is 
        hard (set value) or soft (add value) for variable j. If str, all interventions have 
        the same type.
    seed : int, optional (default: None)
        Random seed.

    Returns
    -------
    data : array-like
        Data generated from this process, shape (T, N).
    nonstationary : bool
        Indicates whether data has NaNs or infinities.

    """
    random_state = np.random.RandomState(seed)

    N = len(links.keys())
    if noises is None:
        noises = [random_state.randn for j in range(N)]

    if N != max(links.keys())+1 or N != len(noises):
        raise ValueError("links and noises keys must match N.")

    # Check parameters
    max_lag = 0
    contemp_dag = _Graph(N)
    for j in range(N):
        for link_props in links[j]:
            var, lag = link_props[0]
            coeff = link_props[1]
            func = link_props[2]
            if lag == 0: contemp = True
            if var not in range(N):
                raise ValueError("var must be in 0..{}.".format(N-1))
            if 'float' not in str(type(coeff)):
                raise ValueError("coeff must be float.")
            if lag > 0 or type(lag) != int:
                raise ValueError("lag must be non-positive int.")
            max_lag = max(max_lag, abs(lag))

            # Create contemp DAG
            if var != j and lag == 0:
                contemp_dag.addEdge(var, j)

    if contemp_dag.isCyclic() == 1: 
        raise ValueError("Contemporaneous links must not contain cycle.")

    causal_order = contemp_dag.topologicalSort() 

    if intervention is not None:
        if intervention_type is None:
            intervention_type = {j:'hard' for j in intervention}
        elif isinstance(intervention_type, str):
            intervention_type = {j:intervention_type for j in intervention}
        for j in intervention.keys():
            if len(intervention[j]) != T:
                raise ValueError("intervention array for j=%s must be of length T = %d" %(j, T))
            if j not in intervention_type.keys():        
                raise ValueError("intervention_type dictionary must contain entry for %s" %(j))

    transient = int(math.floor(.2*T))

    data = np.zeros((T+transient, N), dtype='float32')
    for j in range(N):
        data[:, j] = noises[j](T+transient)

    for t in range(max_lag, T+transient):
        for j in causal_order:

            if (intervention is not None and j in intervention and t >= transient
                and np.isnan(intervention[j][t - transient]) == False):
                if intervention_type[j] == 'hard':
                    data[t, j] = intervention[j][t - transient]
                    # Move to next j and skip link_props-loop from parents below 
                    continue
                else:
                    data[t, j] += intervention[j][t - transient]

            # This loop is only entered if intervention_type != 'hard'
            for link_props in links[j]:
                var, lag = link_props[0]
                coeff = link_props[1]
                func = link_props[2]
                data[t, j] += coeff * func(data[t + lag, var])

    data = data[transient:]

    nonstationary = (np.any(np.isnan(data)) or np.any(np.isinf(data)))

    return data, nonstationary

def structural_causal_process_DBN(links, discrete, T, noises=None,
                        intervention=None, intervention_type='hard', 
                        fixed_prob=None,
                        seed=None):
    """Returns a structural causal process with contemporaneous and lagged
    dependencies.

    Generates generalized additive noise model process of the form

    .. math:: X^j_t = \\eta^j_t + \\sum_{X^i_{t-\\tau}\\in \\mathcal{P}(X^j_t)}
              c^i_{\\tau} f^i_{\\tau}(X^i_{t-\\tau})

    Links have the format ``{0:[((i, -tau), coeff, func),...], 1:[...],
    ...}`` where ``func`` can be an arbitrary (nonlinear) function provided
    as a python callable with one argument and coeff is the multiplication
    factor. The noise distributions of :math:`\\eta^j` can be specified in
    ``noises``.

    Parameters
    ----------
    links : dict
        Dictionary of format: {0:[((i, -tau), coeff, func),...], 1:[...],
        ...} for all variables where i must be in [0..N-1] and tau >= 0 with
        number of variables N. coeff must be a float and func a python
        callable of one argument.
    T : int
        Sample size.
    noises : list of callables, optional (default: 'np.random.randn')
        Random distribution function that is called with noises[j](T).
    intervention : dict
        Dictionary of format: {1:np.array, ...} containing only keys of intervened
        variables with the value being the array of length T with interventional values.
        Set values to np.nan to leave specific values of a variable un-intervened.
    intervention_type : str or dict
        Dictionary of format: {1:'hard',  3:'soft', ...} to specify whether intervention is
        hard (set value) or soft (add value) for variable j. If str, all interventions have
        the same type.
    seed : int, optional (default: None)
        Random seed.

    Returns
    -------
    data : array-like
        Data generated from this process, shape (T, N).
    nonstationary : bool
        Indicates whether data has NaNs or infinities.

    """
    random_state = np.random.default_rng(seed)
    N = len(links.keys())

    # Check parameters
    max_lag = 0
    contemp_dag = _Graph(N)
    for j in range(N):
        for link_props in links[j]:
            # Discrete parents
            var, lag = link_props
            if lag == 0: contemp = True
            if var not in range(N):
                raise ValueError("var must be in 0..{}.".format(N-1))
            if lag > 0 or type(lag) != int:
                raise ValueError("lag must be non-positive int.")
            max_lag = max(max_lag, abs(lag))

            # Create contemp DAG
            if var != j and lag == 0:
                contemp_dag.addEdge(var, j)

    if contemp_dag.isCyclic() == 1:
        raise ValueError("Contemporaneous links must not contain cycle.")

    causal_order = contemp_dag.topologicalSort()

    '''if intervention is not None:
        if intervention_type is None:
            intervention_type = {j:'hard' for j in intervention}
        elif isinstance(intervention_type, str):
            intervention_type = {j:intervention_type for j in intervention}
        for j in intervention.keys():
            if len(intervention[j]) != T:
                raise ValueError("intervention array for j=%s must be of length T = %d" %(j, T))
            if j not in intervention_type.keys():        
                raise ValueError("intervention_type dictionary must contain entry for %s" %(j))'''

    transient = int(math.floor(0.2*T))

    # prob is a 2xN multidimensional matrix. (1xN) for nodes upto max_lag (without parents) and (1xN) of
    # conditional probabilities for the rest of the nodes. The cpm for a N is assumed to be same over all the time
    # points
    prob = np.zeros((2, N), dtype='object')
    # data (filled by drawing from a multinomial distribution from prob)
    data = np.zeros((T + transient, N), dtype='object')
    data[:] = np.nan
    # Order of parents(ids) for each node. This is required to keep track the order to condition on while sampling from
    # cpm
    parents_order = np.zeros((T + transient, N), dtype='object')

    # Initial probabilities to use upto max_lag for each variable. The prob remains same upto max_lag for a variable
    for j in range(N):
        n_cat = discrete.get(j)
        prob[0, j] = stochastic_matrix(random_state, n_cat)

    # Conditional probabilities for all nodes > max_lag. cpm remains the same over all the time points for a variable
    for t in range(max_lag, T+transient):
        for j in causal_order:
            # Interventions
            '''if (intervention is not None and j in intervention and t >= transient
                    and np.isnan(intervention[j][t - transient]) == False):
                if intervention_type[j] == 'hard':
                    data[t, j] = intervention[j][t - transient]
                    continue
                else:
                    data[t, j] += intervention[j][t - transient]'''

            # Number of categories of child - j
            n_cat_j = discrete.get(j)
            # all parents (var, lag) for a node at (t, j)
            categories = []
            parents_idx = []
            for link_props in links[j]:
                # var - parent, j - child
                var, lag = link_props
                parents_idx.append((t + lag, var))
                # Number of categories of parent (var). Categories of var==(var, t+lag)
                n_cat_var = discrete.get(var)
                categories.append(n_cat_var)

            # last element is the number of categories of child-j
            categories.append(n_cat_j)
            # Store parent's ids
            parents_order[t, j] = parents_idx

            # Conditional Probability Matrix (cpm) for each j with parents (vars, lags)
            # The cpm is a ND matrix of size categories = [n_cat_var1, n_cat_var2,..., n_cat_j]
            # If no parents, then categories = [n_cat_j] and cpm will be a stochastic array of size n_cat_j

            # Create a zero matrix of size categories and then fill up over last axis(child) with stochastic array of
            # size = n_cat_j
            # cpm calculated only at one time point. Remains same across all the time points for a j
            if t == max_lag:
                cpm = np.zeros(categories, dtype='object')
                # Fill in instances of stochastic matrix at the last axis, i.e axis of j
                cpm = np.apply_along_axis(lambda x: stochastic_matrix(random_state, n_cat_j, fixed_prop=fixed_prob), axis=len(cpm.shape)-1,
                                          arr=cpm)
                prob[1, j] = cpm

    # Sampling
    for t in range(T + transient):
        for j in causal_order:
            if data[t, j] is np.nan:
                if t < max_lag:
                    draw = random_state.multinomial(1, pvals=prob[0, j], size=1)[0]
                    data[t, j] = np.where(draw == 1)[0][0]
                else:
                    parents = []
                    for p in parents_order[t, j]:
                        parents.append(data[p])
                    conditioned_cpm = prob[1, j][tuple(parents)]
                    draw = random_state.multinomial(1, pvals=conditioned_cpm, size=1)[0]
                    data[t, j] = np.where(draw == 1)[0][0]
            else:
                raise ValueError("Causal order not traversed")

    data = data[transient:].astype(int)

    #nonstationary = (np.any(np.isnan(data)) or np.any(np.isinf(data)))
    return data

def structural_causal_process_DBN_linkstrength(links, discrete, T, n_symbs, intervention=None, intervention_type='hard',
                        seed_p=None, seed_s=None):
    """Returns a Dynamic Bayesian Network (with link strength) as a structural causal process with contemporaneous and
    lagged dependencies.

    Links have the format ``{0:[((i, -tau), eta),...], 1:[...],
    ...}`` where ``eta`` is the link strength between 0 and 1.

    Parameters
    ----------
    links : dict
        Dictionary of format: {0:[((i, -tau), eta),...], 1:[...],
        ...} for all variables where i must be in [0..N-1] and tau >= 0 with
        number of variables N. coeff must be a float between 0 and 1.
    T : int
        Sample size.

    intervention : dict
    intervention_type : str or dict

    seed_p : int, optional (default: None)
        Random seed for CPT generation.
    seed_s : int, optional (default: None)
        Random seed for sampling from the Bayesian Network.

    Returns
    -------
    data : array-like
        Data generated from this process, shape (T, N).

    """
    random_state_prob = np.random.default_rng(seed_p)
    random_state_sample = np.random.default_rng(seed_s)
    N = len(links.keys())

    # Check parameters
    max_lag = 0
    contemp_dag = _Graph(N)
    for j in range(N):
        for link_props in links[j]:
            # Discrete parents
            var, lag = link_props[0]
            eta = link_props[1]
            if lag == 0: contemp = True
            if var not in range(N):
                raise ValueError("var must be in 0..{}.".format(N-1))
            if lag > 0 or type(lag) != int:
                raise ValueError("lag must be non-positive int.")
            if (0 > eta) or (eta > 1):
                raise ValueError("eta must be within [0, 1]")
            max_lag = max(max_lag, abs(lag))

            # Create contemp DAG
            if var != j and lag == 0:
                contemp_dag.addEdge(var, j)

    if contemp_dag.isCyclic() == 1:
        raise ValueError("Contemporaneous links must not contain cycle.")

    causal_order = contemp_dag.topologicalSort()

    '''if intervention is not None:
        if intervention_type is None:
            intervention_type = {j:'hard' for j in intervention}
        elif isinstance(intervention_type, str):
            intervention_type = {j:intervention_type for j in intervention}
        for j in intervention.keys():
            if len(intervention[j]) != T:
                raise ValueError("intervention array for j=%s must be of length T = %d" %(j, T))
            if j not in intervention_type.keys():        
                raise ValueError("intervention_type dictionary must contain entry for %s" %(j))'''

    transient = int(math.floor(0.2*T))

    # prob is a 2xN multidimensional matrix. (1xN) for nodes upto max_lag (without parents) and (1xN) of
    # conditional probabilities for the rest of the nodes. The cpm for a j in N is assumed to be same over all the time
    # points (stationarity assumption).
    prob = np.zeros((2, N), dtype='object')
    # data (filled by drawing from a multinomial distribution from prob)
    data = np.zeros((T + transient, N), dtype='object')
    data[:] = np.nan
    # Order of parents(ids) for each node. This is required to keep track the order to condition on while sampling from
    # cpm
    parents_order = np.zeros((T + transient, N), dtype='object')

    # Initial probabilities to use upto max_lag for each variable. The prob remains same upto max_lag for a variable
    for j in range(N):
        n_cat = discrete.get(j)
        prob[0, j] = stochastic_matrix(random_state_prob, n_cat)

    # Conditional probabilities for all nodes > max_lag. cpm remains the same over all the time points for a variable
    for t in range(max_lag, T+transient):
        for j in causal_order:
            # Interventions
            '''if (intervention is not None and j in intervention and t >= transient
                    and np.isnan(intervention[j][t - transient]) == False):
                if intervention_type[j] == 'hard':
                    data[t, j] = intervention[j][t - transient]
                    continue
                else:
                    data[t, j] += intervention[j][t - transient]'''

            # Number of categories of child - j
            n_cat_j = discrete.get(j)
            # all parents (var, lag) for a node at (t, j)
            parents_idx = []
            categories = []
            etas = []
            for link_props in links[j]:
                # var - parent, j - child
                var, lag = link_props[0]
                eta = link_props[1]
                parents_idx.append((t + lag, var))
                etas.append(eta)
                # Number of categories of parent (var). Categories of var==(var, t+lag)
                n_cat_var = discrete.get(var)
                categories.append(n_cat_var)

            # Add last element as the number of categories of child-j
            categories.append(n_cat_j)
            # Store parent's ids
            parents_order[t, j] = parents_idx

            # Conditional Probability Matrix (cpm) for each j with parents (vars, lags, eta)
            # The cpm is a ND matrix of size categories = [n_cat_var1, n_cat_var2,..., n_cat_j]
            # If no parents, then categories = [n_cat_j] and cpm will be a stochastic array of size n_cat_j
            # cpm calculated only at one time point. Remains same across all the time points for a j
            if t == max_lag:
                if not parents_idx:
                    cpm = stochastic_matrix(random_state_prob, n_cat_j)
                else:
                    cpm = gen_cpt(len(parents_idx), np.arange(n_symbs), np.array(etas))
                prob[1, j] = cpm

    # Sampling
    for t in range(T + transient):
        for j in causal_order:
            if data[t, j] is np.nan:
                if t < max_lag:
                    # Draw a category from multiple categories based on prob.
                    draw = random_state_sample.multinomial(1, pvals=prob[0, j], size=1)[0]
                    data[t, j] = np.where(draw == 1)[0][0]
                else:
                    parents = []
                    for p in parents_order[t, j]:
                        parents.append(data[p])
                    conditioned_cpm = prob[1, j][tuple(parents)]
                    draw = random_state_sample.multinomial(1, pvals=conditioned_cpm, size=1)[0]
                    data[t, j] = np.where(draw == 1)[0][0]
            else:
                raise ValueError("Causal order not traversed")

    data = data[transient:].astype(int)
    return data


def gen_cpt(nparents, var_states, eta):
    ''' Example:
        nparents = 3 - Number of parents.
        var_states = ['A', 'B', 'C'] - The list of states each parent can take.
        eta = [0.5, 0.5, 0.5] - List of link strengths from each parent to child.'''

    nparents = nparents
    states = var_states
    eta = eta

    # P(ui'|ui)
    def P_uid_ui(m, eta):
        P = np.zeros((m, m))
        for r in range(m):
            for c in range(m):
                if r == c:
                    P[r, c] = (1 / m) + (eta * (1 - (1 / m)))

                else:
                    P[r, c] = (1 / (m - 1)) * (1 - (1 / m) - (eta * (1 - (1 / m))))
        return P

    # x=F(u')
    def F(x, ud, eta):
        abs_eta = abs(eta)
        j_ = int(np.around(np.sum(np.multiply(abs_eta, ud)) / np.sum(abs_eta)))
        return x[j_-1]

    m = len(states)
    states = np.arange(m)+1

    x = np.copy(states)
    # Setup P_uid_ui(m, eta) for each parent (No child required).
    P_ud_u = np.zeros((nparents), dtype='object')
    for k in range(nparents):
        P_ud_u[k] = P_uid_ui(m, eta[k])

    # Permutation set of all configurations of u and ud in the order [u1,u1d, u2,u2d, u3,u3d...]
    perm_states = np.array(list(itertools.product(states, repeat=nparents * 2)))
    # Splits into parent subarray configs [u1,u1d], [u2,u2d], [u3,u3d]
    parents = np.array(np.split(perm_states, nparents, axis=1))

    # x = m states, u=pow(m, nparents) state permutations
    P_x_u = np.zeros((pow(m, nparents), m))
    # State permutations of u
    u_states = np.array(list(itertools.product(states, repeat=nparents)))

    # For each perm in perm_states(u and ud)
    for i in range(len(perm_states)):
        x_state = F(x, parents[:, i, 1], eta)
        x_state -= 1
        u_state_index = np.where((u_states == parents[:, i, 0]).all(axis=1))[0][0]

        product_prob = 1.0
        for j in range(nparents):
            product_prob *= P_ud_u[j][(parents[j, i, 1]-1, parents[j, i, 0]-1)]

        P_x_u[u_state_index, x_state] += product_prob
        if P_x_u[u_state_index, x_state] > 1.0:
            P_x_u[u_state_index, x_state] = 1.0

    # Reshape array compatible with conditional probability matrix size = [n_cat_var1, n_cat_var2, n_cat_var3, n_cat_j]
    P_x_u = P_x_u.reshape([m] * (nparents+1))
    return P_x_u

def stochastic_matrix(random_state, n_categories):
    mat = random_state.random(n_categories)
    mat /= mat.sum()
    return mat

def _get_minmax_lag(links):
    """Helper function to retrieve tau_min and tau_max from links.
    """

    N = len(links)

    # Get maximum time lag
    min_lag = np.inf
    max_lag = 0
    for j in range(N):
        for link_props in links[j]:
            if len(link_props) > 2:
                var, lag = link_props[0]
                coeff = link_props[1]
                # func = link_props[2]
                if coeff != 0.:
                    min_lag = min(min_lag, abs(lag))
                    max_lag = max(max_lag, abs(lag))
            else:
                var, lag = link_props
                min_lag = min(min_lag, abs(lag))
                max_lag = max(max_lag, abs(lag))   

    return min_lag, max_lag

def _get_parents(links, exclude_contemp=False):
    """Helper function to parents from links
    """

    N = len(links)

    # Get maximum time lag
    parents = {}
    for j in range(N):
        parents[j] = []
        for link_props in links[j]:
            var, lag = link_props[0]
            coeff = link_props[1]
            # func = link_props[2]
            if coeff != 0.:
                if not (exclude_contemp and lag == 0):
                    parents[j].append((var, lag))

    return parents

def _get_children(parents):
    """Helper function to children from parents
    """

    N = len(parents)
    children = dict([(j, []) for j in range(N)])

    for j in range(N):
        for par in parents[j]:
            i, tau = par
            children[i].append((j, abs(tau)))

    return children


def links_to_graph(links, tau_max=None):
    """Helper function to convert dictionary of links to graph array format.

    Parameters
    ---------
    links : dict
        Dictionary of form {0:[((0, -1), coeff, func), ...], 1:[...], ...}.
        Also format {0:[(0, -1), ...], 1:[...], ...} is allowed.
    tau_max : int or None
        Maximum lag. If None, the maximum lag in links is used.

    Returns
    -------
    graph : array of shape (N, N, tau_max+1)
        Matrix format of graph with 1 for true links and 0 else.
    """

    N = len(links)

    # Get maximum time lag
    min_lag, max_lag = _get_minmax_lag(links)

    # Set maximum lag
    if tau_max is None:
        tau_max = max_lag
    else:
        if max_lag > tau_max:
            raise ValueError("tau_max is smaller than maximum lag = %d "
                             "found in links, use tau_max=None or larger "
                             "value" % max_lag)

    graph = np.zeros((N, N, tau_max + 1), dtype='<U3')
    for j in links.keys():
        for link_props in links[j]:
            if len(link_props) > 2:
                var, lag = link_props[0]
                coeff = link_props[1]
                if coeff != 0.:
                    graph[var, j, abs(lag)] = "-->"
                    if lag == 0:
                        graph[j, var, 0] = "<--"
            else:
                var, lag = link_props
                graph[var, j, abs(lag)] = "-->"
                if lag == 0:
                    graph[j, var, 0] = "<--"

    return graph

class _Logger(object):
    """Class to append print output to a string which can be saved"""
    def __init__(self):
        self.terminal = sys.stdout
        self.log = ""       # open("log.dat", "a")

    def write(self, message):
        self.terminal.write(message)
        self.log += message  # .write(message)


if __name__ == '__main__':
    
    ## Generate some time series from a structural causal process
    def lin_f(x): return x
    def nonlin_f(x): return (x + 5. * x**2 * np.exp(-x**2 / 20.))

    links = {0: [((0, -1), 0.9, lin_f)],
             1: [((1, -1), 0.8, lin_f), ((0, -1), 0.3, nonlin_f)],
             2: [((2, -1), 0.7, lin_f), ((1, 0), -0.2, lin_f)],
             }
    noises = [np.random.randn, np.random.randn, np.random.randn]
    data, nonstat = structural_causal_process(links,
     T=100, noises=noises)
    print(data.shape)

    # Construct graph
    # links = {0: [(0, -1)],
    #          1: [(1, -1), (0, -1)],
    #          2: [(2, -1), (1, 0),],
    #          }
    print(links_to_graph(links))
