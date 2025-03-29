import os
import json
import pickle
import joblib
import pandas as pd
from flask import Flask, jsonify, request
from peewee import (
    SqliteDatabase, PostgresqlDatabase, Model, IntegerField,
    FloatField, TextField, IntegrityError
)
from playhouse.shortcuts import model_to_dict


########################################
# Begin database stuff

DB = SqliteDatabase('predictions.db')


class Prediction(Model):
    observation_id = IntegerField(unique=True)
    observation = TextField()
    proba = FloatField()
    true_class = IntegerField(null=True)

    class Meta:
        database = DB


DB.create_tables([Prediction], safe=True)

# End database stuff
########################################

########################################
# Unpickle the previously-trained model


with open(os.path.join('data', 'columns.json')) as fh:
    columns = json.load(fh)


with open(os.path.join('data', 'pipeline.pickle'), 'rb') as fh:
    pipeline = joblib.load(fh)


with open(os.path.join('data', 'dtypes.pickle'), 'rb') as fh:
    dtypes = pickle.load(fh)


# End model un-pickling
########################################

########################################
# Input validation functions

def attempt_predict(request):
    """
    Produce prediction for request.
    
    Inputs:
        request: dictionary with the format described below
        {
            "observation_id": <id-as-a-string>,
            "data": {
                "age": <value>,
                "sex": <value>,
                "race": <value>,
                "workclass": <value>,
                "education": <value>,
                "marital-status": <value>,
                "capital-gain": <value>,
                "capital-loss": <value>,
                "hours-per-week": <value>,
            }
        }
     
    Returns: A dictionary with predictions or an error, the two potential values:
                if the request is OK and was properly parsed and predicted:
                {
                    "observation_id": <id-of-request>,
                    "prediction": <True|False>,
                    "probability": <probability generated by model>
                }
                otherwise:
                {
                    "observation_id": <id-of-request>,
                    "error": "some error message"
                }
    """
    if 'observation_id' not in request:
        return {"observation_id": None, "error": "observation_id not found in request"}
    
    if 'data' not in request:
        return {"observation_id": request["observation_id"], "error": "`data` not found in request"}
    
    data = request['data']
    
    request_columns = data.keys()
    valid_columns = {
        "age",
        "sex",
        "race",
        "workclass",
        "education",
        "marital-status",
        "capital-gain",
        "capital-loss",
        "hours-per-week",
    }
    
    for column in request_columns:
        if column not in valid_columns:
            return {"observation_id": request["observation_id"], "error": "{} not a valid feature".format(column)}

    for column in valid_columns:
        if column not in request_columns:
            return {"observation_id": request["observation_id"], "error": "{} is missing and is required".format(column)}
    
    categorical_values_map = {
        'sex': ['Male', 'Female'],
        'race': ['White', 'Black','Asian-Pac-Islander', 'Amer-Indian-Eskimo', 'Other'],
        'workclass': ['Private', 'Self-emp-not-inc', 'Local-gov', '?', 'State-gov', 'Self-emp-inc', 'Federal-gov', 'Without-pay', 'Never-worked'],
         'education': ['HS-grad', 'Some-college', 'Bachelors', 'Masters', 'Assoc-voc', '11th', 'Assoc-acdm', '10th', '7th-8th', 'Prof-school', '9th', '12th', 'Doctorate', '5th-6th', '1st-4th', 'Preschool'],
         'marital-status': ['Married-civ-spouse', 'Never-married', 'Divorced', 'Separated', 'Widowed', 'Married-spouse-absent', 'Married-AF-spouse']}

    for feature in categorical_values_map.keys():
        allowed_values = categorical_values_map[feature]
        if data[feature] not in allowed_values:
            return {"observation_id": request["observation_id"], 
                    "error": "{}: {} is not a valid value for this feature".format(feature, data[feature])}
    
    age = data["age"]
    if not isinstance(age, int) or age < 0 or age > 200:
        return {"observation_id": request["observation_id"], 
                "error": "{}: {} is not a valid value for this feature".format("age", data["age"])}

    hours_per_week = data["hours-per-week"]
    if (not isinstance(hours_per_week, int) and not isinstance(hours_per_week, float))  or hours_per_week < 0 or hours_per_week > 168:
        return {"observation_id": request["observation_id"], 
                "error": "{}: {} is not a valid value for this feature".format("hours-per-week", data["hours-per-week"])}

    capital_gain = data["capital-gain"]
    if (not isinstance(capital_gain, int) and not isinstance(capital_gain, float)) or capital_gain < 0:
        return {"observation_id": request["observation_id"], 
                "error": "{}: {} is not a valid value for this feature".format("capital-gain", data["capital-gain"])}

    capital_loss = data["capital-loss"]
    if (not isinstance(capital_loss, int) and not isinstance(capital_loss, float)) or capital_loss < 0:
        return {"observation_id": request["observation_id"], 
                "error": "{}: {} is not a valid value for this feature".format("capital-loss", data["capital-loss"])}

    observation = request['data']
    observation_df = pd.DataFrame([observation], columns=columns).astype(dtypes)
    prediction = pipeline.predict(observation_df)[0]
    probability = pipeline.predict_proba(observation_df)[0, 1]
    response = {
        'observation_id': request['observation_id'],
        'prediction': bool(prediction),
        'probability': probability
    } 
    
    return response


# End input validation functions
########################################

########################################
# Begin webserver stuff

app = Flask(__name__)


@app.route('/predict', methods=['POST'])
def predict():
    obs_dict = request.get_json()

   #obs = pd.DataFrame([observation], columns=columns).astype(dtypes)
   
    response =attempt_predict(obs_dict)
    if 'error' in response:
        return jsonify(response)
    _probability = response.get("probability")
    _id = response.get("observation_id")
    p = Prediction(
        observation_id=_id,
        proba=_probability,
        observation=request.data,
    )
    try:
        p.save()
    except IntegrityError:
        error_msg = "ERROR: Observation ID: '{}' already exists".format(_id)
        response["error"] = error_msg
        print(error_msg)
        DB.rollback()
    return jsonify(response)

    
@app.route('/update', methods=['POST'])
def update():
    obs = request.get_json()
    try:
        p = Prediction.get(Prediction.observation_id == obs['id'])
        p.true_class = obs['true_class']
        p.save()
        return jsonify(model_to_dict(p))
    except Prediction.DoesNotExist:
        error_msg = 'Observation ID: "{}" does not exist'.format(obs['id'])
        return jsonify({'error': error_msg})


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=5000)
