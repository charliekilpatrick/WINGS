from typing import List

from django.shortcuts import render
from django.urls import reverse
from pipelinesite.models import Jobs, Events


def job_single_view(request, pk):
    #TODO: Tree view of events and parent events
    # Events page would have jobs that created it and teh job that came from it
    job = Jobs.objects.get(pk=pk)
    # all_jobs = session.query(Job).all()
    # print("ALL THE JOBS:", all_jobs)
    # job = session.query(Job).get(pk) # Sqlalchemy notation

    print('job id and name:', job.id, job)
    try:
        job_stack = jobs_stack_generator(job, 2, 2)
    except Exception as exc:
        print('Falling back to Django job stack:', exc)
        job_stack = django_job_stack(job)

    print("OUR JOB STACK:", job_stack)

    # sql_alchemy_firing_event = wp.Event.query.filter(id=job.firing_event.id).all()
    # sql_alchemy_firing_event = session.query(Event).get(job.firing_event.id)
    # print("sql alchemy firing event:", sql_alchemy_firing_event)

    context = {'job': job, 'job_stack': job_stack}

    return render(request, 'job/job_single_view.html', context)

# TODO: Add traversing events into this
def events_stack_generator(base_firing_event: Events, parent_count: int, child_count: int) -> dict:
    events_stack = []

    # Process child events
    current_event = base_firing_event
    for i in range(child_count):
        # Check that a child event exists
        # TODO: How do we get the child event?
        # if current_event.
        # current_event =
        events_stack.append({'value': f'test base_event{(child_count-i)*".child"}', 'url': None})

    # Process the base_firing_even

    events_stack.append({'value': f'The base event: ({base_firing_event.id}) {base_firing_event.name}',
                         'url': reverse('manager:event_detail_view', args=[base_firing_event.id])})

    # To properly add these parent jobs to our stack while making traversing easy we need a sub stack that we reverse
    # and extend onto the original stack
    # TODO: Did I hit the end?
    current_event = base_firing_event
    parent_sub_stack = []
    # TODO: Bug on parent firing event
    for i in range(parent_count):
        # Check that there is a parent job and parent job firing_event. Otherwise we break
        if current_event.parent_job is None or current_event.parent_job.firing_event is None:
            print("There were some nones")
            break
        print("Why are we here")
        # Passed out check, assign the current event as the next parent firing event
        current_event = base_firing_event.parent_job.firing_event
        print("parent count: ", i, current_event)

        parent_sub_stack.append({'value': f'Event name: ({current_event.id}) {current_event.name} | {(parent_count-i)*".parent"}',
                                 'url': reverse('manager:event_detail_view', args=[base_firing_event.id])})

    events_stack.extend(parent_sub_stack[::-1])

    print([x['value'] for x in events_stack])
    print([x['value'] for x in events_stack][::-1])

    # TODO: Add some ending indicator if there isn't any parent or children. This can be figured out from the
    return events_stack

# TODO: Get child event for a job.  Then to get it's latest job we would look at the event and use the self.fired_jobs[-1]
#

def django_job_stack(job: 'Jobs') -> List[dict]:
    """Parent/child job chain using Django models only (no wpipe MySQL session)."""
    stack = []
    current = job
    parents = []
    seen = {job.pk}
    for _ in range(5):
        event = current.firing_event
        if event is None or event.parent_job_id is None:
            break
        parent = event.parent_job
        if parent is None or parent.pk in seen:
            break
        seen.add(parent.pk)
        parents.append({
            'value': f'Parent job ({parent.pk}) {parent.task} [{parent.state}]',
            'url': reverse('manager:job_single_view', args=[parent.pk]),
        })
        current = parent
    stack.extend(reversed(parents))
    stack.append({
        'value': f'This job ({job.pk}) {job.task} [{job.state}]',
        'url': reverse('manager:job_single_view', args=[job.pk]),
    })
    for ev in Events.objects.filter(parent_job=job):
        stack.append({
            'value': f'Child event ({ev.pk}) {ev.name}',
            'url': reverse('manager:event_detail_view', args=[ev.pk]),
        })
        for child_job in Jobs.objects.filter(firing_event=ev):
            stack.append({
                'value': f'Child job ({child_job.pk}) {child_job.task} [{child_job.state}]',
                'url': reverse('manager:job_single_view', args=[child_job.pk]),
            })
    return stack


def jobs_stack_generator(base_job: 'Jobs', parent_count: int, child_count: int) -> List[dict]:

    from wpipe.Job import Job as WpipeJob

    jobs_stack = []
    print("base_job:", base_job)
    wpipe_base_job = WpipeJob(int(base_job.pk))

    print("THE WPIPE BASE JOB:", wpipe_base_job)
    print("THE WPIPE PARENT JOB:", wpipe_base_job.parent_job)
    print("THE WPIPE PARENT TASK NAME:", wpipe_base_job.task.name)
    print('Wpipe parent jobs:', wpipe_base_job.parent_job)
    print('wpipe child events: ', wpipe_base_job.child_events)
    children = wpipe_base_job.child_events
    print('wpipe child event:', wpipe_base_job.child_event)
    print([child for child in children])

    # Process child jobs
    current_job = base_job
    for i in range(child_count):
        # Check that a child event exists
        # TODO: How do we get the child job?
        # if current_event.
        # current_event =
        jobs_stack.append({'value': f'test base_job{(child_count - i) * ".child"}', 'url': None})

    # Process the base_job

    jobs_stack.append({'value': f'The base job: ({base_job.id}) ',
                         'url': reverse('manager:job_single_view', args=[base_job.id])})

    # To properly add these parent jobs to our stack while making traversing easy we need a sub stack that we reverse
    # and extend onto the original stack
    current_job = wpipe_base_job
    print(f"base job: {current_job.job_id}")
    print(f"parent-base-job: {current_job.parent_job.job_id}")
    print(f"parent-parent-base-job: {current_job.parent_job.parent_job.job_id}")
    parent_sub_stack = []
    for i in range(parent_count):
        # Check that there is a parent job and parent job firing_event. Otherwise we break
        if current_job.firing_event is None or current_job.parent_job is None:
            print("There were some nones")
            break
        # Passed out check, assign the current event as the next parent firing event
        current_job = current_job.parent_job
        print(f'parent count: {parent_count}')
        print(f"current parent job id: {current_job.job_id}")
        parent_sub_stack.append(
            {'value': f'Job name: ({current_job.job_id}) {(parent_count - i) * ".parent"}'})



    jobs_stack.extend(parent_sub_stack[::-1])

    print([x['value'] for x in jobs_stack])
    print([x['value'] for x in jobs_stack][::-1])

    # TODO: Add some ending indicator if there isn't any parent or children. This can be figured out from the
    return jobs_stack