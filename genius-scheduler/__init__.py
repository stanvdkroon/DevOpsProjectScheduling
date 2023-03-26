import logging

import azure.functions as func

import numpy as np
import weakref
from tabulate import tabulate
import copy
import random
import collections
import json

class Randomize(object):
    def __init__(self, timetable, iterations=100):
        self.timetable = timetable
        self.iterations = iterations

    def run(self):
        count = 0
        while not self.randomize():
            if count >= self.iterations:
                raise Exception("No valid random solution found.")
            count += 1
        return self.timetable

    def randomize(self, perfect_fit=False):
        config = self.timetable.config
        self.timetable.reset()
        assistants = list(self.timetable.assistants.values())

        for day in range(config.day_count):
            for time in range(config.time_slots_count):
                for count in range(config.max_occupation):
                    if self.timetable.tt.roster[day][time][count]:
                        random.shuffle(assistants)
                        error_count = 0
                        for assistant in assistants:
                            if assistant.rostered < assistant.hours and assistant not in list(self.timetable.tt.roster[day, time]):
                                self.timetable.tt.roster[day][time][count] = assistant
                                assistant.rostered += 1
                                break
                            error_count += 1
                        if error_count == len(assistants):
                            if perfect_fit:
                                return False
                            self.timetable.tt.roster[day][time][count] = None
        return True


class Hillclimber(object):
    def __init__(self, timetable, swaps = 250):
        self.timetable = timetable
        self.swaps = swaps

    def run(self, swaps = None):
        self.hill_climber(swaps)

    def reset(self):
        return

    def hill_climber(self, swaps = None):
        """
        A stochastic hill climber which swaps two random seminars with eachother a
        number of times. Also does student swaps because fuck yeah.
        main: The roster which will be used by random_seminar_swap_hill_climber
        swaps: The amount of swaps made before returning.
        night_slot: A boolean that says yes we can make america better.
        """
        maximum = self.timetable.tt.score

        if not swaps:
            swaps = self.swaps

        # Run this a number of "swaps" times.
        swaps += self.timetable.evaluations

        while self.timetable.evaluations < swaps:

            # The standard seminar swap, copy the roster but with a random swap,
            # make the copy the main roster if better and not otherwise.
            tmp_roster = self.timetable.tt.xopt(2)
            if tmp_roster.score >= maximum:
                self.timetable.tt = tmp_roster
                maximum = tmp_roster.score

        return self.timetable.tt


class Assistant(object):
    """
    Represents an assistant with identification
    """

    def __init__(self, name, uid, availability, availability_matrix, hours):
        """

        """
        self.name = name

        # JSON formatted availability
        self.availability = availability

        # Availability: rows = time_slots, columns = days
        self.matrix = np.array(availability_matrix)

        self.hours = hours
        self.rostered = 0

        self.uid = int(uid)

    def is_available(self, index):
        if self.matrix[index] != 0:
            return True
        return False

    def __eq__(self, other):
        if not type(other) == type(self):
            return False
        return self.uid == other.uid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return self.uid

    def __repr__(self):
        """

        """
        return f"{self.name}"


class Config(object):
    """
    A config class to contain the list of student, course and room objects that
    are relevant to the roster they are used for in a timetable.
    """

    def __init__(self, staff, project):
        """
        Requires object lists generated in the initialize module.
        """
        self.staff = staff

        self.days = project.get('columns')
        self.time_slots = project.get('rows')
        self.occupation = [[int(project.get('schedule')[slot][day]) for slot in self.time_slots] for day in self.days]

        self.assistants = {assistant.uid: assistant for assistant in self.init_assistants()}

        self.slots_name = 'slots'
        self.day_count = len(self.days)
        self.time_slots_count = len(self.time_slots)
        self.assistant_count = len(self.assistants)
        self.max_occupation = max([max(hours) for hours in self.occupation])

        self.roster_indices = self.get_indices(self.init_roster())

        self.available_indices = self.roster_indices

    def init_assistants(self):
        assistants = []

        for assistant in self.staff:
            name = assistant.get('name')
            assistant_id = assistant.get('id')
            availability = assistant.get('schedule')
            availability_matrix = [[availability[slot][day] for slot in self.time_slots] for day in self.days]
            periods = assistant.get('periods')
            assistants.append(Assistant(name, assistant_id, availability, availability_matrix, periods))
            
        return assistants

    def init_roster(self):
        roster = np.array(
            [[[True for day in range(self.max_occupation)] for time_slot in range(self.time_slots_count)] for hours
             in range(self.day_count)], dtype=object)
        for day in range(self.day_count):
            for time_slot in range(self.time_slots_count):
                for count in range(self.max_occupation - self.occupation[day][time_slot]):
                    roster[day][time_slot][-1 - count] = False

        return roster

    def get_indices(self, roster):
        indices = []
        for day in range(self.day_count):
            for time_slot in range(self.time_slots_count):
                for count in range(self.max_occupation):
                    if roster[day][time_slot][count]:
                        indices.append((day, time_slot, count))

        return indices


class Roster(object):
    """
    Main roster class in which all lectures will be scheduled.
    """
    def __init__(self, config, timetable):
        """
        Create a roster consisting of (room, day, timeslot)
        This object has a hidden parent that is a Timetable object.
        """
        self.config = config
        self.roster = config.init_roster()

        self._score_calculated = False
        self._score = None
        self.parent = weakref.ref(timetable)

    @property
    def score(self):
        self.parent().evaluations += 1
        return calculate(self)
        # if not self._score_calculated:
        #     self._score = scorefunction.calculate(self)
        #     self._score_calculated = True
        #
        #     # NOTE: Dit is een lelijke oplossing om evaluations bij te houden.
        #     self.parent().evaluations += 1
        #     if self._score > self.parent().best:
        #         self.parent().best = self._score
        #     self.parent().evaluation_data.append((self.parent().evaluations, self._score, self.parent().best))
        #
        # return self._score

    def roster_activity(self, day, time, assistant):
        """
        Schedule a seminar object into the roster at specified location.
        """
        self.roster[day, time].append(weakref.ref(assistant))

    def deepcopy(self):
        """
        Deepcopy and set attributes of a roster.
        """
        roster_out = copy.deepcopy(self)
        roster_out._score_calculated = False
        return roster_out

    def valid_target(self, targets, indices):
        if not indices or not targets:
            return False

        # if None in targets:
        #     return False

        for i, index in enumerate(indices):
            for j, other in enumerate(indices):
                if i != j and self.roster[index] in self.roster[other[:2]]:
                    return False
        return True

    def random_elements(self, n):
        targets = []
        indices = []
        while not self.valid_target(targets, indices):
            # Get a list of unique indices for an array of roster shape
            indices = self.config.available_indices

            random.shuffle(indices)
            indices = indices[:n]
            # targets = list(itertools.chain.from_iterable([self.roster[index[:2]] for index in indices]))
            targets = [self.roster[index] for index in indices]

        # Shuffle the indices in-place
        random.shuffle(indices)

        return indices

    def xopt(self, n=3, indices=None):
        tt_out = self.deepcopy()

        if not indices:
            indices = tt_out.random_elements(n)

        dummy = tt_out.roster[indices[0]]

        for i in range(1, n):
            tt_out.roster[indices[i - 1]] = tt_out.roster[indices[i]]

        tt_out.roster[indices[-1]] = dummy

        return tt_out

    def __hash__(self):
        return hash(self.__repr__())

    def __repr__(self):
        return self.roster

    def __str__(self):
        return tabulate(self.roster)


class Timetable(object):
    """
    A governing timetable class to contain a roster in which seminars are
    rostered. And a config file which contains relevant info for a roster.
    """
    def __init__(self, config, roster=None):
        """
        Initializes with a roster and a config object.
        Automatically weakrefs itself as a parent of the roster object.
        """
        self.config = config

        if roster:
            self.adopt_roster(roster)
        else:
            self.tt = Roster(config, self)

        # NOTE: Dit hoort ergens anders, maar heb het maar hier gestopt.
        self.evaluation_data = []
        self.evaluations = 0
        self.best = -float('inf')

        self.assistants = copy.deepcopy(config.assistants)

    def to_json(self):
        return json.dumps({
            'columns': self.config.days,
            'rows': self.config.time_slots,
            'schedule': {
                    slot: { 
                        day: [assistant.name if assistant else 'x' for assistant in self.tt.roster[col_index][slot_index]]
                        for col_index, day in enumerate(self.config.days)
                    } 
                for slot_index, slot in enumerate(self.config.time_slots)
            }
        })

    @property
    def score(self):
        return self.tt.score

    def deepcopy(self):
        temp_timetable = Timetable(self.config, self.tt.deepcopy())
        temp_timetable.evaluation_data = copy.copy(self.evaluation_data)
        temp_timetable.evaluations = self.evaluations
        temp_timetable.best = self.best

        return temp_timetable

    def reset(self):
        self.__init__(self.config)

    def adopt_roster(self, roster):
        """
        Replaces the current roster with a new one and sets parent accordingly.
        """
        self.tt = roster
        self.tt.parent = weakref.ref(self)

    def __str__(self):
        return tabulate(self.tt.roster)


def calculate(tt):
    """

    """
    score = 100
    assistants = tt.parent().assistants

    indices = list(np.ndindex(tt.roster.shape))

    assistant_schedule = collections.defaultdict(lambda: collections.defaultdict(dict))

    for index in indices:
        if tt.roster[index]:
            assistant = assistants[tt.roster[index].uid]
            assistant_schedule[assistant][tuple([index[0], index[1]])] = True
            if assistant.matrix[index[:2]] == 0:
                score -= 100

    for index in indices:
        if tt.roster[index]:
            assistant = assistants[tt.roster[index].uid]
            if not assistant_schedule[assistant][tuple([index[0], index[1] - 1])] and \
                    not assistant_schedule[assistant][tuple([index[0], index[1] + 1])]:
                score -= 1

    for assistant, schedule in assistant_schedule.items():
        indices = [key for key, item in schedule.items() if item is True]
        hour_count = 1
        for i, index in enumerate(indices[1:]):
            prev_index = indices[i]
            if index[0] == prev_index[0]:
                hour_count += 1

                if index[1] - prev_index[1] != 1:
                    score -= 100
            else:
                hour_count = 1

            if hour_count > 4:
                score -= (hour_count - 4) * 5

    return score

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    staff = req.params.get('staff')
    if not staff:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            staff = req_body.get('staff')

    project = req.params.get('project')
    if not project:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            project = req_body.get('project')

    config = Config(staff, project)

    main_timetable = Timetable(config)

    randomize = Randomize(main_timetable)
    randomize.run()

    alg = Hillclimber(main_timetable)
    alg.run(20000)
    
    return func.HttpResponse(alg.timetable.to_json())   
