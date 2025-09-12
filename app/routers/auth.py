from fastapi import APIRouter
router = APIRouter(prefix='/auth')

@router.get('/login')
def login():
    return {'msg':'login ok'}
