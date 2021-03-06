# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2016, Numenta, Inc.  Unless you have an agreement
# with Numenta, Inc., for a separate license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

"""
This evaluates the effect of synapse sampling on the feedforward and lateral
connections of L2. Specifically, how low can we go with L2 activation threshold,
number of distal synapses and number of proximal synapses while still get
reliable performance.

We consider the problem of multi-column convergence.
"""

import random
import os
import pprint
import numpy as np
import pandas as pd
import cPickle
from multiprocessing import Pool
import matplotlib.pyplot as plt
plt.ion()

from htmresearch.frameworks.layers.l2_l4_inference import L4L2Experiment
from htmresearch.frameworks.layers.object_machine_factory import (
  createObjectMachine
)


def getL4Params():
  """
  Returns a good default set of parameters to use in the L4 region.
  """
  return {
    "columnCount": 2048,
    "cellsPerColumn": 8,
    "formInternalBasalConnections": False,
    "learningMode": True,
    "inferenceMode": True,
    "learnOnOneCell": False,
    "initialPermanence": 0.51,
    "connectedPermanence": 0.6,
    "permanenceIncrement": 0.1,
    "permanenceDecrement": 0.02,
    "minThreshold": 10,
    "predictedSegmentDecrement": 0.002,
    "activationThreshold": 13,
    "maxNewSynapseCount": 20,
    "defaultOutputType": "predictedActiveCells",
    "implementation": "etm_cpp",
    "seed": 41
  }



def getL2Params():
  """
  Returns a good default set of parameters to use in the L4 region.
  """
  return {
    "columnCount": 1024,
    "inputWidth": 2048 * 8,
    "learningMode": True,
    "inferenceMode": True,
    "initialPermanence": 0.41,
    "connectedPermanence": 0.5,
    "permanenceIncrement": 0.1,
    "permanenceDecrement": 0.02,
    "numActiveColumnsPerInhArea": 40,
    "synPermProximalInc": 0.1,
    "synPermProximalDec": 0.001,
    "initialProximalPermanence": 0.6,
    "minThresholdDistal": 10,
    "minThresholdProximal": 10,
    "predictedSegmentDecrement": 0.002,
    "activationThresholdDistal": 13,
    "maxNewProximalSynapseCount": 20,
    "maxNewDistalSynapseCount": 20,
    "maxSynapsesPerDistalSegment": 255,
    "maxSynapsesPerProximalSegment": 2000,
    "seed": 41
  }


def locateConvergencePoint(stats, targetValue):
  """
  Walk backwards through stats until you locate the first point that diverges
  from targetValue.  We need this to handle cases where it might get to
  targetValue, diverge, and then get back again.  We want the last convergence
  point.
  """
  for i,v in enumerate(stats[::-1]):
    if v != targetValue:
      return len(stats)-i

  # Never differs - converged right away
  return 0


def averageConvergencePoint(inferenceStats, prefix, targetValue):
  """
  Given inference statistics for a bunch of runs, locate all traces with the
  given prefix. For each trace locate the iteration where it finally settles
  on targetValue. Return the average settling iteration across all runs.
  """
  itSum = 0
  itNum = 0
  for stats in inferenceStats:
    for key in stats.iterkeys():
      if prefix in key:
        itSum += locateConvergencePoint(stats[key], targetValue)
        itNum += 1

  return float(itSum)/itNum


def runExperiment(args):
  """
  Run experiment.  What did you think this does?

  args is a dict representing the parameters. We do it this way to support
  multiprocessing. args contains one or more of the following keys:

  @param noiseLevel  (float) Noise level to add to the locations and features
                             during inference. Default: None
  @param profile     (bool)  If True, the network will be profiled after
                             learning and inference. Default: False
  @param numObjects  (int)   The number of objects we will train.
                             Default: 10
  @param numPoints   (int)   The number of points on each object.
                             Default: 10
  @param numLocations (int)  For each point, the number of locations to choose
                             from.  Default: 10
  @param numFeatures (int)   For each point, the number of features to choose
                             from.  Default: 10
  @param numColumns  (int)   The total number of cortical columns in network.
                             Default: 2

  The method returns the args dict updated with two additional keys:
    convergencePoint (int)   The average number of iterations it took
                             to converge across all objects
    objects          (pairs) The list of objects we trained on
  """
  numObjects = args.get("numObjects", 10)
  numLocations = args.get("numLocations", 10)
  numFeatures = args.get("numFeatures", 10)
  numColumns = args.get("numColumns", 2)
  profile = args.get("profile", False)
  noiseLevel = args.get("noiseLevel", None)  # TODO: implement this?
  numPoints = args.get("numPoints", 10)
  trialNum = args.get("trialNum", 42)
  l2Params = args.get("l2Params", getL2Params())
  l4Params = args.get("l4Params", getL4Params())
  objectSeed = args.get("objectSeed", 41)

  # Create the objects
  objects = createObjectMachine(
    machineType="simple",
    numInputBits=20,
    sensorInputSize=1024,
    externalInputSize=1024,
    numCorticalColumns=numColumns,
    seed=objectSeed,
  )
  objects.createRandomObjects(numObjects, numPoints=numPoints,
                                    numLocations=numLocations,
                                    numFeatures=numFeatures)

  # print "Objects are:"
  # for o in objects:
  #   pairs = objects[o]
  #   pairs.sort()
  #   print str(o) + ": " + str(pairs)

  # Setup experiment and train the network
  name = "convergence_O%03d_L%03d_F%03d_C%03d_T%03d" % (
    numObjects, numLocations, numFeatures, numColumns, trialNum
  )
  exp = L4L2Experiment(
    name,
    L2Overrides=l2Params,
    L4Overrides=l4Params,
    numCorticalColumns=numColumns,
    seed=trialNum
  )

  exp.learnObjects(objects.provideObjectsToLearn())
  L2TimeLearn = 0
  L2TimeInfer = 0

  if profile:
    # exp.printProfile(reset=True)
    L2TimeLearn = getProfileInfo(exp)
    args.update({"L2TimeLearn": L2TimeLearn})
  exp.resetProfile()

  # For inference, we will check and plot convergence for each object. For each
  # object, we create a sequence of random sensations for each column.  We will
  # present each sensation for 3 time steps to let it settle and ensure it
  # converges.

  for objectId in objects:
    obj = objects[objectId]

    # Create sequence of sensations for this object for all columns
    objectSensations = {}
    for c in range(numColumns):
      objectCopy = [pair for pair in obj]
      random.shuffle(objectCopy)
      # stay multiple steps on each sensation
      sensations = []
      for pair in objectCopy:
        for _ in xrange(2):
          sensations.append(pair)
      objectSensations[c] = sensations

    inferConfig = {
      "object": objectId,
      "numSteps": len(objectSensations[0]),
      "pairs": objectSensations
    }

    exp.infer(objects.provideObjectToInfer(inferConfig), objectName=objectId)
    if profile:
      L2TimeInfer += getProfileInfo(exp)
      exp.resetProfile()
      # exp.printProfile(reset=True)

  if profile:
    L2TimeInfer /= len(objects)
    args.update({"L2TimeInfer": L2TimeInfer})

  convergencePoint = averageConvergencePoint(
    exp.getInferenceStats(),"L2 Representation", 40)
  print "# distal syn {} # proximal syn {}, # convergence point={}" \
        "train time {} infer time {}".format(
    l2Params["maxNewDistalSynapseCount"],
    l2Params["maxNewProximalSynapseCount"],
    convergencePoint, L2TimeLearn, L2TimeInfer)

  # Return our convergence point as well as all the parameters and objects
  args.update({"objects": objects.getObjects()})
  args.update({"convergencePoint": convergencePoint})

  # Can't pickle experiment so can't return it. However this is very useful
  # for debugging when running in a single thread.
  # args.update({"experiment": exp})
  return args, exp


def getProfileInfo(exp):
  """
  Prints profiling information.

  Parameters:
  ----------------------------
  @param   reset (bool)
           If set to True, the profiling will be reset.

  """

  totalTime = 0.000001
  for region in exp.network.regions.values():
    timer = region.getComputeTimer()
    totalTime += timer.getElapsed()

  # Sort the region names
  regionNames = list(exp.network.regions.keys())
  regionNames.sort()

  count = 1
  profileInfo = []
  L2Time = 0.0
  L4Time = 0.0
  for regionName in regionNames:
    region = exp.network.regions[regionName]
    timer = region.getComputeTimer()
    count = max(timer.getStartCount(), count)
    profileInfo.append([region.name,
                        timer.getStartCount(),
                        timer.getElapsed(),
                        100.0 * timer.getElapsed() / totalTime,
                        timer.getElapsed() / max(timer.getStartCount(), 1)])
    if "L2Column" in regionName:
      L2Time += timer.getElapsed()
    elif "L4Column" in regionName:
      L4Time += timer.getElapsed()
  return L2Time


def experimentVaryingSynapseSampling(maxNewDistalSynapseCountList,
                                     maxNewProximalSynapseCountList):

  numRpts = 20
  df = None
  for maxNewProximalSynapseCount in maxNewProximalSynapseCountList:
    for maxNewDistalSynapseCount in maxNewDistalSynapseCountList:
      for rpt in range(numRpts):
        l4Params = getL4Params()
        l2Params = getL2Params()
        l2Params["maxNewProximalSynapseCount"] = maxNewProximalSynapseCount
        l2Params["minThresholdProximal"] = maxNewProximalSynapseCount
        l2Params["maxNewDistalSynapseCount"] = maxNewDistalSynapseCount
        l2Params["activationThresholdDistal"] = maxNewDistalSynapseCount
        l2Params["minThresholdDistal"] = maxNewDistalSynapseCount

        results, exp = runExperiment(
                      {
                        "numObjects": 10,
                        "numLocations": 10,
                        "numFeatures": 7,
                        "numColumns": 3,
                        "trialNum": rpt,
                        "l4Params": l4Params,
                        "l2Params": l2Params,
                        "profile": True,
                        "objectSeed": rpt,
                      }
        )

        numLateralConnctions = []
        numProximalConnections = []
        for l2Columns in exp.L2Columns:
          numLateralConnctions.append(
            l2Columns._pooler.tm.basalConnections.numSynapses())
          numProximalConnections.append(
            np.sum(l2Columns._pooler.proximalConnections.colSums()))

        result = {
          'trial': rpt,
          'L2TimeLearn': results['L2TimeLearn'],
          'L2TimeInfer': results['L2TimeInfer'],
          'maxNewProximalSynapseCount': maxNewProximalSynapseCount,
          'maxNewDistalSynapseCount': maxNewDistalSynapseCount,
          'numLateralConnctions': np.mean(np.array(numLateralConnctions)),
          'numProximalConnections': np.mean(np.array(numProximalConnections)),
          'convergencePoint': results['convergencePoint']}
        if df is None:
          df = pd.DataFrame.from_dict(result, orient='index')
        else:
          df = pd.concat([df, pd.DataFrame.from_dict(result, orient='index')], axis=1)

  df = df.transpose()
  return df


def experimentVaryingDistalSynapseNumber():
  maxNewDistalSynapseCountList = [2, 3, 4, 5, 6, 8, 10, 15, 20]
  maxNewProximalSynapseCountList = [5]
  df = experimentVaryingSynapseSampling(maxNewDistalSynapseCountList,
                                        maxNewProximalSynapseCountList)
  l2LearnTimeList = []
  l2InferTimeList = []
  convergencePointList =[]
  numLateralConnctionsList = []
  for maxNewDistalSynapseCount in maxNewDistalSynapseCountList:
    idx = np.where(np.logical_and(
      df['maxNewDistalSynapseCount'] == maxNewDistalSynapseCount,
      df['maxNewProximalSynapseCount'] == maxNewProximalSynapseCountList[0]))[0]

    l2LearnTimeList.append(np.mean(df['L2TimeLearn'].iloc[idx]))
    l2InferTimeList.append(np.mean(df['L2TimeInfer'].iloc[idx]))
    convergencePointList.append(np.mean(df['convergencePoint'].iloc[idx]))
    numLateralConnctionsList.append(np.mean(df['numLateralConnctions'].iloc[idx]))

  fig, ax = plt.subplots(2, 2)

  ax[0, 0].plot(maxNewDistalSynapseCountList, convergencePointList, '-o')
  ax[0, 0].set_ylabel('# pts to converge')
  ax[0, 0].set_xlabel('# new distal syns')

  ax[0, 1].plot(maxNewDistalSynapseCountList, numLateralConnctionsList, '-o')
  ax[0, 1].set_ylabel('# lateral connections')
  ax[0, 1].set_xlabel('# new distal syns')

  ax[1, 0].plot(maxNewDistalSynapseCountList, l2LearnTimeList, '-o')
  ax[1, 0].set_ylabel('L2 training time (s)')
  ax[1, 0].set_xlabel('# new distal syns')

  ax[1, 1].plot(maxNewDistalSynapseCountList, l2InferTimeList, '-o')
  ax[1, 1].set_ylabel('L2 infer time (s)')
  ax[1, 1].set_xlabel('# new distal syns')

  plt.tight_layout()
  plt.savefig('plots/L2PoolingDistalSynapseSampling.pdf')


def experimentVaryingProximalSynapseNumber():
  maxNewDistalSynapseCountList = [5]
  maxNewProximalSynapseCountList = [1, 2, 3, 4, 5, 6, 8, 10, 15]
  df = experimentVaryingSynapseSampling(maxNewDistalSynapseCountList,
                                        maxNewProximalSynapseCountList)
  l2LearnTimeList = []
  l2InferTimeList = []
  convergencePointList =[]
  numProximalConnctionsList = []
  for maxNewProximalSynapseCount in maxNewProximalSynapseCountList:
    idx = np.where(np.logical_and(
      df['maxNewDistalSynapseCount'] == maxNewDistalSynapseCountList[0],
      df['maxNewProximalSynapseCount'] == maxNewProximalSynapseCount))[0]

    l2LearnTimeList.append(np.mean(df['L2TimeLearn'].iloc[idx]))
    l2InferTimeList.append(np.mean(df['L2TimeInfer'].iloc[idx]))
    convergencePointList.append(np.mean(df['convergencePoint'].iloc[idx]))
    numProximalConnctionsList.append(np.mean(df['numProximalConnections'].iloc[idx]))

  fig, ax = plt.subplots(2, 2)

  ax[0, 0].plot(maxNewProximalSynapseCountList, convergencePointList, '-o')
  ax[0, 0].set_ylabel('# pts to converge')
  ax[0, 0].set_xlabel('# new proximal syns')

  ax[0, 1].plot(maxNewProximalSynapseCountList, numProximalConnctionsList, '-o')
  ax[0, 1].set_ylabel('# lateral connections')
  ax[0, 1].set_xlabel('# new proximal syns')

  ax[1, 0].plot(maxNewProximalSynapseCountList, l2LearnTimeList, '-o')
  ax[1, 0].set_ylabel('L2 training time (s)')
  ax[1, 0].set_xlabel('# new proximal syns')

  ax[1, 1].plot(maxNewProximalSynapseCountList, l2InferTimeList, '-o')
  ax[1, 1].set_ylabel('L2 infer time (s)')
  ax[0, 1].set_xlabel('# new proximal syns')

  plt.tight_layout()
  plt.savefig('plots/L2PoolingProximalSynapseSampling.pdf')


if __name__ == "__main__":
  # Fixed number of proximal synapses, varying distal synapse sampling
  # experimentVaryingDistalSynapseNumber()

  # Fixed number of distal synapses, varying distal synapse sampling
  experimentVaryingProximalSynapseNumber()
