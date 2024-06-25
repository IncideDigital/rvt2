from easyjobs import simplejob
from base.job import BaseModule

@simplejob(params_help=dict(
    count='Number of times the message must be returned',
    name='The name of the user'
))
def test(ctx: BaseModule, name: str = 'Alice', count: int = 0):
    """ A test for a simplejob.

    It will show "Hello NAME" a number of times, using counter() to show
    how simple jobs can call each other.
    """
    for i in counter()(to=count):
        yield dict(greetings=f'Hello {name} count+1={count+1} from_module={ctx.from_module}')


@simplejob()
def counter(to: int = 10):
    """ A test for a simplejob: return numbers from 0 to optional parameter to """
    return range(0, to)
